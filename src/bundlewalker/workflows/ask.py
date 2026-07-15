from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from bundlewalker.agents.common import AgentDependencies, resolve_model
from bundlewalker.agents.query import (
    AgentModel,
    run_query_agent,
    validate_cited_answer,
)
from bundlewalker.changes import ChangeValidationContext, validate_change_set
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    CitedAnswer,
    ConceptType,
    DraftConcept,
)
from bundlewalker.errors import AgentRunError, OkfError, UsageError, WorkspaceError
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


@dataclass(frozen=True, slots=True)
class AnsweredQuestion:
    answer: CitedAnswer
    read_ids: frozenset[str]


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
    repository = OkfRepository(workspace.wiki_dir)
    model = resolve_model(explicit_model, environment if environment is not None else os.environ)
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions=conventions,
        root_index=root_index,
    )
    selected_runner = runner if runner is not None else run_query_agent
    answer, reported_reads = await selected_runner(model, dependencies, question)
    actual_reads = frozenset(dependencies.read_ids)
    if reported_reads != actual_reads:
        raise AgentRunError("query runner read history does not match the actual read ledger")
    validate_cited_answer(answer, repository, actual_reads)
    return AnsweredQuestion(answer=answer, read_ids=actual_reads)


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
        description="A saved answer to a knowledge query.",
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
