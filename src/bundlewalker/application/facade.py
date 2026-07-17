"""Workspace-bound async read use cases shared by delivery adapters."""

import binascii
import unicodedata
from base64 import b64decode, urlsafe_b64encode
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import NoReturn
from urllib.parse import quote

from bundlewalker.application.contracts import (
    MAX_CONCEPT_PAGE_SIZE,
    MAX_QUESTION_CHARACTERS,
    MAX_SEARCH_CHARACTERS,
    AnswerResult,
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    ConceptSummaryResult,
    IngestionResult,
    InlineSource,
    LintResult,
    MutationResult,
    PendingReviewSummary,
    RefreshResult,
    ReviewResult,
    SynthesisResult,
    WorkspaceStatus,
)
from bundlewalker.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    translate_error,
)
from bundlewalker.domain import MAX_CONCEPT_ID_CHARACTERS, OkfDocument
from bundlewalker.errors import BundleWalkerError, TransactionError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.transactions import (
    TransactionReview,
    apply_pending_review,
    discard_pending_review,
    ensure_no_pending_review,
    get_pending_review,
    recover_transactions,
)
from bundlewalker.workflows import ask as ask_workflow
from bundlewalker.workflows import ingest as ingest_workflow
from bundlewalker.workflows import lint as lint_workflow
from bundlewalker.workspace import Workspace, load_inline_source

_INVALID_CONCEPT_ID_MESSAGE = "concept ID must be a normalized relative path"
_INVALID_CURSOR_MESSAGE = "concept cursor is invalid"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    environment: Mapping[str, str] | None = None
    ingestion_runner: ingest_workflow.IngestionRunner | None = None
    query_runner: ask_workflow.QueryRunner | None = None
    refresh_runner: ask_workflow.RefreshQueryRunner | None = None
    semantic_lint_runner: lint_workflow.SemanticLintRunner | None = None
    clock: Callable[[], datetime] = _utc_now


class WorkspaceApplication:
    """Adapter-neutral, asynchronous use cases bound to one workspace."""

    def __init__(
        self,
        workspace: Workspace,
        dependencies: ApplicationDependencies | None = None,
    ) -> None:
        self.workspace = workspace
        self.dependencies = dependencies or ApplicationDependencies()

    async def status(self) -> WorkspaceStatus:
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan().values()
            counts = Counter(document.metadata.type for document in documents)
            pending = get_pending_review(self.workspace)
            return WorkspaceStatus(
                display_name=self.workspace.root.name,
                config_version=self.workspace.config.version,
                concept_counts=dict(sorted(counts.items())),
                pending_review=_to_review_summary(pending),
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def list_concepts(
        self,
        *,
        cursor: str | None = None,
        limit: int = MAX_CONCEPT_PAGE_SIZE,
    ) -> ConceptPage:
        if not 1 <= limit <= MAX_CONCEPT_PAGE_SIZE:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                f"concept page limit must be between 1 and {MAX_CONCEPT_PAGE_SIZE}",
            )
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan()
            ordered_ids = sorted(documents)
            start = _cursor_start(ordered_ids, cursor)
            selected = ordered_ids[start : start + limit]
            next_cursor = (
                _encode_cursor(selected[-1])
                if selected and start + limit < len(ordered_ids)
                else None
            )
            return ConceptPage(
                items=tuple(_concept_summary(documents[concept_id]) for concept_id in selected),
                next_cursor=next_cursor,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def read_concept(self, concept_id: str) -> ConceptContent:
        _validate_public_concept_id(concept_id)
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan()
            document = documents.get(concept_id)
            if document is None:
                raise ApplicationError(
                    ApplicationErrorCode.CONCEPT_NOT_FOUND,
                    f"concept does not exist: {concept_id}",
                )
            summary = _concept_summary(document)
            markdown = document.path.read_text(encoding="utf-8")
            return ConceptContent(
                **summary.model_dump(),
                markdown=markdown,
                digest=document.digest,
            )
        except ApplicationError:
            raise
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc
        except OSError as exc:
            raise ApplicationError(
                ApplicationErrorCode.OKF_ERROR,
                "concept could not be read",
            ) from exc

    async def search_concepts(
        self,
        query: str,
        *,
        concept_type: str | None = None,
        limit: int = 10,
    ) -> ConceptSearchResult:
        if not query.strip() or len(query) > MAX_SEARCH_CHARACTERS:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                "search query must be non-empty and within the supported limit",
            )
        try:
            recover_transactions(self.workspace)
            repository = OkfRepository(self.workspace.wiki_dir)
            matches = LexicalRetriever(repository).search(query, concept_type, limit)
            documents = repository.scan()
            return ConceptSearchResult(
                items=tuple(_concept_summary(documents[item.concept_id]) for item in matches)
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def ask(self, question: str, *, explicit_model: str | None) -> AnswerResult:
        if len(question) > MAX_QUESTION_CHARACTERS:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                "question exceeds the supported limit",
            )
        try:
            answered = await ask_workflow.answer_question(
                self.workspace,
                question,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.query_runner,
            )
            rendered = ask_workflow.render_cited_answer(
                answered.answer,
                OkfRepository(self.workspace.wiki_dir),
            )
            return AnswerResult(answer=answered.answer, markdown=rendered)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def lint(self, *, semantic: bool, explicit_model: str | None) -> LintResult:
        try:
            result = await lint_workflow.run_lint(
                self.workspace,
                semantic=semantic,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.semantic_lint_runner,
            )
            return LintResult(
                findings=result.findings,
                deterministic_has_errors=result.deterministic_has_errors,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def get_pending_review(self) -> ReviewResult | None:
        try:
            return _to_review_result(get_pending_review(self.workspace))
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def prepare_file_ingestion(
        self,
        source_path: Path,
        *,
        explicit_model: str | None,
    ) -> IngestionResult:
        try:
            outcome = await ingest_workflow.prepare_ingestion(
                self.workspace,
                source_path,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.ingestion_runner,
                occurred_at=self.dependencies.clock(),
            )
            return _ingestion_result(self.workspace, outcome)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def prepare_ingestion(
        self,
        source: InlineSource,
        *,
        explicit_model: str | None,
    ) -> IngestionResult:
        try:
            recover_transactions(self.workspace)
            raw_source = load_inline_source(source.source_name, source.content, self.workspace)
            outcome = await ingest_workflow.prepare_raw_ingestion(
                self.workspace,
                raw_source,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.ingestion_runner,
                occurred_at=self.dependencies.clock(),
            )
            return _ingestion_result(self.workspace, outcome)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def prepare_synthesis(
        self,
        question: str,
        *,
        explicit_model: str | None,
    ) -> SynthesisResult:
        try:
            ensure_no_pending_review(self.workspace)
            answered = await ask_workflow.answer_question(
                self.workspace,
                question,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.query_runner,
            )
            ask_workflow.prepare_synthesis(
                self.workspace,
                answered,
                occurred_at=self.dependencies.clock(),
            )
            review = _required_review_result(self.workspace)
            rendered = ask_workflow.render_cited_answer(
                answered.answer,
                OkfRepository(self.workspace.wiki_dir),
            )
            return SynthesisResult(
                answer=AnswerResult(answer=answered.answer, markdown=rendered),
                review=review,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def prepare_refresh(
        self,
        instruction: str,
        concept_id: str,
        *,
        explicit_model: str | None,
    ) -> RefreshResult:
        try:
            ensure_no_pending_review(self.workspace)
            refreshed = await ask_workflow.answer_synthesis_refresh(
                self.workspace,
                instruction,
                concept_id,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.refresh_runner,
            )
            rendered = ask_workflow.render_cited_answer(
                refreshed.answer,
                OkfRepository(self.workspace.wiki_dir),
            )
            answer = AnswerResult(answer=refreshed.answer, markdown=rendered)
            outcome = ask_workflow.prepare_synthesis_refresh(
                self.workspace,
                refreshed,
                occurred_at=self.dependencies.clock(),
            )
            if isinstance(outcome, ask_workflow.SynthesisAlreadyCurrent):
                return RefreshResult(
                    status="current",
                    concept_id=outcome.concept_id,
                    answer=answer,
                    review=None,
                )
            return RefreshResult(
                status="pending",
                concept_id=refreshed.target.concept_id,
                answer=answer,
                review=_required_review_result(self.workspace),
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def apply_review(self, review_id: str) -> MutationResult:
        try:
            apply_pending_review(self.workspace, review_id)
            return MutationResult(review_id=review_id, status="applied")
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def discard_review(self, review_id: str) -> MutationResult:
        try:
            discard_pending_review(self.workspace, review_id)
            return MutationResult(review_id=review_id, status="discarded")
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc


def _concept_summary(document: OkfDocument) -> ConceptSummaryResult:
    return ConceptSummaryResult(
        concept_id=document.concept_id,
        type=document.metadata.type,
        title=document.metadata.title or PurePosixPath(document.concept_id).name,
        description=document.metadata.description or "",
        tags=tuple(document.metadata.tags),
        resource_uri=f"bundlewalker://concept/{quote(document.concept_id, safe='/')}",
    )


def _to_review_summary(review: TransactionReview | None) -> PendingReviewSummary | None:
    if review is None:
        return None
    return PendingReviewSummary(
        review_id=review.review_id,
        kind=review.kind,
        status=review.status,
        summary=review.summary,
    )


def _to_review_result(review: TransactionReview | None) -> ReviewResult | None:
    if review is None:
        return None
    return ReviewResult(
        review_id=review.review_id,
        kind=review.kind,
        status=review.status,
        summary=review.summary,
        diff=review.diff,
        changed_paths=review.changed_paths,
        created_at=review.created_at,
        resource_uri="bundlewalker://review/pending",
    )


def _required_review_result(workspace: Workspace) -> ReviewResult:
    review = _to_review_result(get_pending_review(workspace))
    if review is None:
        raise TransactionError("workflow preparation returned without a pending review")
    return review


def _ingestion_result(
    workspace: Workspace,
    outcome: ingest_workflow.IngestionOutcome,
) -> IngestionResult:
    if isinstance(outcome, ingest_workflow.DuplicateIngestion):
        return IngestionResult(status="duplicate", review=None)
    return IngestionResult(status="pending", review=_required_review_result(workspace))


def _encode_cursor(concept_id: str) -> str:
    return urlsafe_b64encode(concept_id.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_start(ordered_ids: list[str], cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor:
        _raise_invalid_cursor()
    try:
        padding = "=" * (-len(cursor) % 4)
        concept_id = b64decode(cursor + padding, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        _raise_invalid_cursor()
    if _encode_cursor(concept_id) != cursor:
        _raise_invalid_cursor()
    try:
        _validate_public_concept_id(concept_id)
    except ApplicationError:
        _raise_invalid_cursor()
    for index, candidate in enumerate(ordered_ids):
        if candidate > concept_id:
            return index
    return len(ordered_ids)


def _validate_public_concept_id(concept_id: str) -> None:
    path = PurePosixPath(concept_id)
    if (
        not concept_id
        or len(concept_id) > MAX_CONCEPT_ID_CHARACTERS
        or "\\" in concept_id
        or any(unicodedata.category(character) == "Cc" for character in concept_id)
        or path.is_absolute()
        or path == PurePosixPath(".")
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != concept_id
    ):
        raise ApplicationError(ApplicationErrorCode.INVALID_INPUT, _INVALID_CONCEPT_ID_MESSAGE)


def _raise_invalid_cursor() -> NoReturn:
    raise ApplicationError(ApplicationErrorCode.INVALID_INPUT, _INVALID_CURSOR_MESSAGE)
