from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from pydantic import ValidationError

from bundlewalker.agents.common import AgentDependencies, resolve_model
from bundlewalker.agents.query import (
    AgentModel,
    run_query_agent,
    run_refresh_query_agent,
    validate_cited_answer,
)
from bundlewalker.changes import ChangeValidationContext, render_draft, validate_change_set
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    OkfDocument,
)
from bundlewalker.errors import (
    AgentRunError,
    ChangeSetError,
    OkfError,
    UsageError,
    WorkspaceError,
)
from bundlewalker.okf.documents import document_digest
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.transactions import PreparedTransaction, prepare_transaction, recover_transactions
from bundlewalker.workflows.context import (
    open_workspace_directory,
    read_context,
    safe_configured_parts,
    validate_repository_path,
)
from bundlewalker.workspace import Workspace

type QueryRunner = Callable[
    [AgentModel, AgentDependencies, str],
    Awaitable[tuple[CitedAnswer, frozenset[str]]],
]
type RefreshQueryRunner = Callable[
    [AgentModel, AgentDependencies, str, OkfDocument],
    Awaitable[tuple[CitedAnswer, frozenset[str]]],
]

_CANONICAL_SYNTHESIS_ID = re.compile(r"^syntheses/[a-z0-9]+(?:-[a-z0-9]+)*$")
_DEFAULT_SYNTHESIS_DESCRIPTION = "A saved answer to a knowledge query."


@dataclass(frozen=True, slots=True)
class AnsweredQuestion:
    answer: CitedAnswer
    read_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class AnsweredSynthesisRefresh:
    answer: CitedAnswer
    read_ids: frozenset[str]
    target: OkfDocument


@dataclass(frozen=True, slots=True)
class SynthesisAlreadyCurrent:
    concept_id: str


async def answer_question(
    workspace: Workspace,
    question: str,
    *,
    explicit_model: str | None,
    environment: Mapping[str, str] | None = None,
    runner: QueryRunner | None = None,
) -> AnsweredQuestion:
    """Recover interrupted persistence, then run and validate one cited query."""
    recover_transactions(workspace)
    if not question.strip():
        raise UsageError("question must not be empty")

    validate_repository_path(workspace)
    repository = OkfRepository(workspace.wiki_dir)
    dependencies = _query_dependencies(workspace, repository)
    model = resolve_model(explicit_model, environment if environment is not None else os.environ)
    selected_runner = runner if runner is not None else run_query_agent
    answer, reported_reads = await selected_runner(model, dependencies, question)
    actual_reads = frozenset(dependencies.read_ids)
    if reported_reads != actual_reads:
        raise AgentRunError("query runner read history does not match the actual read ledger")
    validate_cited_answer(answer, repository, actual_reads)
    return AnsweredQuestion(answer=answer, read_ids=actual_reads)


async def answer_synthesis_refresh(
    workspace: Workspace,
    question: str,
    concept_id: str,
    *,
    explicit_model: str | None,
    environment: Mapping[str, str] | None = None,
    runner: RefreshQueryRunner | None = None,
) -> AnsweredSynthesisRefresh:
    """Recover, validate one refresh target, then run one cited revision query."""
    recover_transactions(workspace)
    if not question.strip():
        raise UsageError("question must not be empty")

    validate_repository_path(workspace)
    repository = OkfRepository(workspace.wiki_dir)
    target = _load_refresh_target(repository, concept_id)
    dependencies = _query_dependencies(workspace, repository)
    model = resolve_model(explicit_model, environment if environment is not None else os.environ)
    selected_runner = runner if runner is not None else run_refresh_query_agent
    answer, reported_reads = await selected_runner(model, dependencies, question, target)
    actual_reads = frozenset(dependencies.read_ids)
    if reported_reads != actual_reads:
        raise AgentRunError("query runner read history does not match the actual read ledger")
    _validate_no_refresh_self_citation(answer, target.concept_id)
    validate_cited_answer(answer, repository, actual_reads)
    return AnsweredSynthesisRefresh(
        answer=answer,
        read_ids=actual_reads,
        target=target,
    )


def prepare_synthesis(
    workspace: Workspace,
    answered: AnsweredQuestion,
    *,
    occurred_at: datetime | None = None,
) -> PreparedTransaction:
    """Convert a validated answer into one reviewed Synthesis transaction."""
    recover_transactions(workspace)
    validate_repository_path(workspace)
    repository = OkfRepository(workspace.wiki_dir)
    validate_cited_answer(answered.answer, repository, answered.read_ids)
    slug = _available_synthesis_slug(workspace, answered.answer.title)
    draft = DraftConcept(
        operation=ChangeOperation.CREATE,
        path=f"syntheses/{slug}",
        type=ConceptType.SYNTHESIS,
        title=answered.answer.title,
        description=_DEFAULT_SYNTHESIS_DESCRIPTION,
        tags=["synthesis"],
        body=answered.answer.body,
        citations=answered.answer.citations,
    )
    change_set = ChangeSet(
        summary=f"Saved synthesis: {answered.answer.title}",
        drafts=[draft],
    )
    context = ChangeValidationContext(
        mode="synthesis",
        repository=repository,
        readable_concepts=answered.read_ids,
    )
    validate_change_set(change_set, context)
    return prepare_transaction(
        workspace,
        change_set,
        context,
        None,
        occurred_at or datetime.now(UTC),
    )


def prepare_synthesis_refresh(
    workspace: Workspace,
    refresh: AnsweredSynthesisRefresh,
    *,
    occurred_at: datetime | None = None,
) -> PreparedTransaction | SynthesisAlreadyCurrent:
    """Build one reviewed in-place Synthesis replacement, or report a canonical no-op."""
    recover_transactions(workspace)
    validate_repository_path(workspace)
    repository = OkfRepository(workspace.wiki_dir)
    validate_cited_answer(refresh.answer, repository, refresh.read_ids)
    _validate_no_refresh_self_citation(refresh.answer, refresh.target.concept_id)
    description = refresh.target.metadata.description
    draft = DraftConcept(
        operation=ChangeOperation.REPLACE,
        path=refresh.target.concept_id,
        type=ConceptType.SYNTHESIS,
        title=refresh.answer.title,
        description=(description if description is not None else _DEFAULT_SYNTHESIS_DESCRIPTION),
        tags=list(refresh.target.metadata.tags),
        body=refresh.answer.body,
        citations=refresh.answer.citations,
        base_digest=refresh.target.digest,
    )
    change_set = ChangeSet(
        summary=f"Refreshed synthesis: {refresh.answer.title}",
        drafts=[draft],
    )
    context = ChangeValidationContext(
        mode="synthesis",
        repository=repository,
        readable_concepts=refresh.read_ids,
    )
    validate_change_set(change_set, context)

    actual_occurred_at = occurred_at or datetime.now(UTC)
    comparison_time = refresh.target.metadata.timestamp or actual_occurred_at
    canonical = render_draft(draft, context, occurred_at=comparison_time)
    if document_digest(canonical.encode("utf-8")) == refresh.target.digest:
        _require_current_refresh_target(repository, refresh.target)
        return SynthesisAlreadyCurrent(refresh.target.concept_id)
    return prepare_transaction(
        workspace,
        change_set,
        context,
        None,
        actual_occurred_at,
    )


def render_cited_answer(answer: CitedAnswer, repository: OkfRepository) -> str:
    """Render an answer and its structured citations for terminal Markdown output."""
    try:
        documents = repository.scan()
    except OkfError as exc:
        raise AgentRunError("query citations could not be rendered") from exc

    references: list[str] = []
    for citation in sorted(answer.citations, key=lambda item: item.number):
        document = documents.get(citation.concept_id)
        if document is None:
            raise AgentRunError(f"query citation target does not exist: {citation.concept_id}")
        title = document.metadata.title or PurePosixPath(citation.concept_id).name
        escaped_title = title.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
        target = quote(f"/{citation.concept_id}.md", safe="/")
        reference = f"[{citation.number}] [{escaped_title}]({target})"
        if citation.start_line is not None:
            assert citation.end_line is not None
            reference += f" — raw lines {citation.start_line}\u2013{citation.end_line}"
        references.append(reference)
    return f"{answer.body.rstrip()}\n\n# Citations\n\n" + "\n".join(references) + "\n"


def _available_synthesis_slug(workspace: Workspace, title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-") or "synthesis"
    wiki_parts = safe_configured_parts(workspace.config.wiki_dir, "configured wiki path")
    with open_workspace_directory(
        workspace,
        (*wiki_parts, "syntheses"),
        "synthesis category",
    ) as directory:
        try:
            occupied = {name.casefold() for name in os.listdir(directory)}
        except OSError as exc:
            raise WorkspaceError("could not inspect synthesis destinations") from exc

    suffix = 1
    while True:
        slug = base if suffix == 1 else f"{base}-{suffix}"
        if f"{slug}.md".casefold() not in occupied:
            return slug
        suffix += 1


def _query_dependencies(
    workspace: Workspace,
    repository: OkfRepository,
) -> AgentDependencies:
    conventions = read_context(
        workspace,
        workspace.config.conventions_file,
        "workspace conventions",
    )
    root_index = read_context(
        workspace,
        (PurePosixPath(workspace.config.wiki_dir) / "index.md").as_posix(),
        "root index",
    )
    return AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions=conventions,
        root_index=root_index,
    )


def _load_refresh_target(repository: OkfRepository, concept_id: str) -> OkfDocument:
    if _CANONICAL_SYNTHESIS_ID.fullmatch(concept_id) is None:
        raise UsageError(
            "refresh target must be a canonical Synthesis concept ID "
            f"syntheses/<lowercase-ascii-slug>: {concept_id}"
        )
    target = repository.scan().get(concept_id)
    if target is None:
        raise UsageError(f"refresh target does not exist: {concept_id}")
    if target.metadata.type != ConceptType.SYNTHESIS.value:
        raise UsageError(f"refresh target is not a Synthesis: {concept_id}")
    _validate_refresh_target_metadata(target)
    return target


def _validate_refresh_target_metadata(target: OkfDocument) -> None:
    try:
        DraftConcept(
            operation=ChangeOperation.REPLACE,
            path=target.concept_id,
            type=ConceptType.SYNTHESIS,
            title="Refresh target",
            description=(
                target.metadata.description
                if target.metadata.description is not None
                else _DEFAULT_SYNTHESIS_DESCRIPTION
            ),
            tags=list(target.metadata.tags),
            body="Refresh target.",
            base_digest=target.digest,
        )
    except ValidationError:
        raise UsageError("refresh target metadata exceeds supported producer limits") from None


def _require_current_refresh_target(
    repository: OkfRepository,
    target: OkfDocument,
) -> None:
    try:
        current = repository.scan().get(target.concept_id)
    except OkfError:
        current = None
    if current is None or current.digest != target.digest:
        raise ChangeSetError(f"replace target has a stale base digest: {target.concept_id}")


def _validate_no_refresh_self_citation(answer: CitedAnswer, concept_id: str) -> None:
    try:
        cites_self = any(citation.concept_id == concept_id for citation in answer.citations)
    except Exception:
        raise AgentRunError("query citations could not be checked") from None
    if cites_self:
        raise AgentRunError(f"refreshed synthesis cannot cite itself: {concept_id}")
