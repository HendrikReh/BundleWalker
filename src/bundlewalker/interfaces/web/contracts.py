# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Explicit, browser-safe contracts for the local web interface."""

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from bundlewalker.application import (
    MAX_INLINE_SOURCE_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    MAX_SOURCE_NAME_CHARACTERS,
    AnswerResult,
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    ConceptSummaryResult,
    IngestionResult,
    LintResult,
    MutationResult,
    RefreshResult,
    ReviewResult,
    SynthesisResult,
    WorkspaceStatus,
)
from bundlewalker.domain import (
    MAX_CONCEPT_ID_CHARACTERS,
    MAX_LINT_CODE_CHARACTERS,
    MAX_LINT_MESSAGE_CHARACTERS,
    MAX_LINT_REMEDIATION_CHARACTERS,
    MAX_TITLE_CHARACTERS,
    FindingOrigin,
    Severity,
)
from bundlewalker.transactions import ReviewKind, ReviewStatus

MAX_WEB_SOURCE_BYTES: Final = 4_000_000
MAX_WEB_REQUEST_BYTES: Final = 4_100_000
MAX_WEB_MODEL_NAME_CHARACTERS: Final = 255
_REVIEW_ID_PATTERN = r"^[0-9a-f]{32}$"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_ABSOLUTE_PATH_TEXT = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_WINDOWS_UNC_PATH_TEXT = re.compile(r"(?<![\\A-Za-z0-9])\\\\[^\\\s]+\\[^\\\s]+")
_UNIX_ABSOLUTE_PATH_TEXT = re.compile(r"(?<![:A-Za-z0-9])/(?!/)[^\s\"'<>`]+")
_SAFE_SOURCE_MARKDOWN_DESTINATION = re.compile(
    r"(?P<prefix>(?<!!)\[[^\]\r\n]+\]\()"
    r"/sources/[a-z0-9]+(?:-[a-z0-9]+)*\.md"
    r"(?P<close>\))"
)

ModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_WEB_MODEL_NAME_CHARACTERS),
]
ConceptId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS),
]


class _WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WebPendingReviewSummary(_WebModel):
    review_id: str = Field(pattern=_REVIEW_ID_PATTERN)
    kind: ReviewKind
    status: ReviewStatus
    summary: str


class WebWorkspaceResponse(_WebModel):
    display_name: str
    config_version: int
    concept_counts: dict[str, int]
    pending_review: WebPendingReviewSummary | None
    csrf_token: str = Field(min_length=1)


class WebConceptSummary(_WebModel):
    concept_id: ConceptId
    type: str
    title: str
    description: str
    tags: tuple[str, ...]


class WebConceptPageResponse(_WebModel):
    items: tuple[WebConceptSummary, ...]
    next_cursor: str | None


class WebConceptResponse(WebConceptSummary):
    markdown: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WebSearchResponse(_WebModel):
    items: tuple[WebConceptSummary, ...]


class WebAskRequest(_WebModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    model: ModelName | None = None


class WebCitation(_WebModel):
    number: int = Field(ge=1)
    concept_id: ConceptId


class WebAnswerResponse(_WebModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)
    markdown: str
    citations: tuple[WebCitation, ...]


class WebLintRequest(_WebModel):
    semantic: bool = False
    model: ModelName | None = None


class WebLintFinding(_WebModel):
    origin: FindingOrigin
    severity: Severity
    code: str = Field(min_length=1, max_length=MAX_LINT_CODE_CHARACTERS)
    message: str = Field(min_length=1, max_length=MAX_LINT_MESSAGE_CHARACTERS)
    path: str | None = None
    evidence_paths: tuple[str, ...]
    remediation: str | None = Field(
        default=None,
        max_length=MAX_LINT_REMEDIATION_CHARACTERS,
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None:
            _require_safe_relative_path(value)
        return value

    @field_validator("evidence_paths")
    @classmethod
    def validate_evidence_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _require_safe_relative_path(value)
        return values


class WebLintResponse(_WebModel):
    findings: tuple[WebLintFinding, ...]
    deterministic_has_errors: bool


class WebIngestionRequest(_WebModel):
    source_name: str = Field(min_length=1, max_length=MAX_SOURCE_NAME_CHARACTERS)
    content: str = Field(max_length=MAX_INLINE_SOURCE_CHARACTERS)
    model: ModelName | None = None

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        if (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or ":" in value
            or any(unicodedata.category(character) == "Cc" for character in value)
        ):
            raise ValueError("source_name must be one safe filename")
        suffix = next(
            (candidate for candidate in (".md", ".txt") if value.endswith(candidate)),
            None,
        )
        if suffix is None:
            raise ValueError("source_name must end in .md or .txt")
        if not value[: -len(suffix)].strip():
            raise ValueError("source_name must contain a usable filename stem")
        return value

    @field_validator("content")
    @classmethod
    def validate_content_bytes(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        if len(value.encode("utf-8")) > MAX_WEB_SOURCE_BYTES:
            raise ValueError("source content exceeds the UTF-8 byte limit")
        return value


class WebReviewResponse(_WebModel):
    review_id: str = Field(pattern=_REVIEW_ID_PATTERN)
    kind: ReviewKind
    status: ReviewStatus
    summary: str
    diff: str
    changed_paths: tuple[str, ...]
    created_at: AwareDatetime

    @field_validator("changed_paths")
    @classmethod
    def validate_changed_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _require_safe_relative_path(value)
        return values

    @field_validator("summary")
    @classmethod
    def reject_summary_absolute_paths(cls, value: str) -> str:
        if _contains_absolute_path(value):
            raise ValueError("review metadata must not contain absolute paths")
        return value

    @field_validator("diff")
    @classmethod
    def reject_diff_absolute_paths(cls, value: str) -> str:
        if _contains_absolute_path(value, allow_source_markdown_links=True):
            raise ValueError("review metadata must not contain absolute paths")
        return value


class WebIngestionResponse(_WebModel):
    status: Literal["duplicate", "pending"]
    review: WebReviewResponse | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending ingestion must contain exactly one review")
        return self


class WebSynthesisRequest(WebAskRequest):
    pass


class WebSynthesisResponse(_WebModel):
    answer: WebAnswerResponse
    review: WebReviewResponse


class WebRefreshRequest(_WebModel):
    instruction: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    concept_id: ConceptId
    model: ModelName | None = None


class WebRefreshResponse(_WebModel):
    status: Literal["current", "pending"]
    concept_id: ConceptId
    answer: WebAnswerResponse
    review: WebReviewResponse | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending refresh must contain exactly one review")
        return self


class WebMutationResponse(_WebModel):
    review_id: str = Field(pattern=_REVIEW_ID_PATTERN)
    status: Literal["applied", "discarded"]


class WebErrorDetail(_WebModel):
    code: str
    message: str
    retryable: bool
    review_id: str | None = Field(default=None, pattern=_REVIEW_ID_PATTERN)
    diagnostic_id: str | None = Field(default=None, pattern=_REVIEW_ID_PATTERN)


class WebErrorResponse(_WebModel):
    error: WebErrorDetail


def to_web_workspace(
    status: WorkspaceStatus,
    csrf_token: str,
) -> WebWorkspaceResponse:
    """Map workspace status without exposing server or session identity."""
    pending = status.pending_review
    return WebWorkspaceResponse(
        display_name=status.display_name,
        config_version=status.config_version,
        concept_counts=dict(status.concept_counts),
        pending_review=(
            WebPendingReviewSummary(
                review_id=pending.review_id,
                kind=pending.kind,
                status=pending.status,
                summary=pending.summary,
            )
            if pending is not None
            else None
        ),
        csrf_token=csrf_token,
    )


def to_web_concept_page(page: ConceptPage) -> WebConceptPageResponse:
    return WebConceptPageResponse(
        items=tuple(_to_web_concept_summary(item) for item in page.items),
        next_cursor=page.next_cursor,
    )


def to_web_concept(concept: ConceptContent) -> WebConceptResponse:
    summary = _to_web_concept_summary(concept)
    return WebConceptResponse(
        **summary.model_dump(),
        markdown=concept.markdown,
        digest=concept.digest,
    )


def to_web_search(result: ConceptSearchResult) -> WebSearchResponse:
    return WebSearchResponse(items=tuple(_to_web_concept_summary(item) for item in result.items))


def to_web_answer(result: AnswerResult) -> WebAnswerResponse:
    return WebAnswerResponse(
        title=result.answer.title,
        markdown=result.markdown,
        citations=tuple(
            WebCitation(number=citation.number, concept_id=citation.concept_id)
            for citation in result.answer.citations
        ),
    )


def to_web_lint(result: LintResult) -> WebLintResponse:
    return WebLintResponse(
        findings=tuple(
            WebLintFinding(
                origin=finding.origin,
                severity=finding.severity,
                code=finding.code,
                message=finding.message,
                path=finding.path,
                evidence_paths=tuple(finding.evidence_paths),
                remediation=finding.remediation,
            )
            for finding in result.findings
        ),
        deterministic_has_errors=result.deterministic_has_errors,
    )


def to_web_review(review: ReviewResult) -> WebReviewResponse:
    """Map only review fields required to inspect and resolve the proposal."""
    return WebReviewResponse(
        review_id=review.review_id,
        kind=review.kind,
        status=review.status,
        summary=review.summary,
        diff=review.diff,
        changed_paths=review.changed_paths,
        created_at=review.created_at,
    )


def to_web_ingestion(result: IngestionResult) -> WebIngestionResponse:
    return WebIngestionResponse(
        status=result.status,
        review=to_web_review(result.review) if result.review is not None else None,
    )


def to_web_synthesis(result: SynthesisResult) -> WebSynthesisResponse:
    return WebSynthesisResponse(
        answer=to_web_answer(result.answer),
        review=to_web_review(result.review),
    )


def to_web_refresh(result: RefreshResult) -> WebRefreshResponse:
    return WebRefreshResponse(
        status=result.status,
        concept_id=result.concept_id,
        answer=to_web_answer(result.answer),
        review=to_web_review(result.review) if result.review is not None else None,
    )


def to_web_mutation(result: MutationResult) -> WebMutationResponse:
    return WebMutationResponse(review_id=result.review_id, status=result.status)


def _to_web_concept_summary(result: ConceptSummaryResult) -> WebConceptSummary:
    return WebConceptSummary(
        concept_id=result.concept_id,
        type=result.type,
        title=result.title,
        description=result.description,
        tags=result.tags,
    )


def _require_safe_relative_path(value: str) -> None:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not value
        or value.startswith(("/", "\\"))
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("web paths must be safe relative paths")


def _contains_absolute_path(
    value: str,
    *,
    allow_source_markdown_links: bool = False,
) -> bool:
    inspected = (
        _SAFE_SOURCE_MARKDOWN_DESTINATION.sub(
            r"\g<prefix>bundlewalker-source\g<close>",
            value,
        )
        if allow_source_markdown_links
        else value
    )
    if (
        _WINDOWS_ABSOLUTE_PATH_TEXT.search(inspected) is not None
        or _WINDOWS_UNC_PATH_TEXT.search(inspected) is not None
    ):
        return True
    return any(
        match.group().rstrip(".,);]}") != "/dev/null"
        for match in _UNIX_ABSOLUTE_PATH_TEXT.finditer(inspected)
    )
