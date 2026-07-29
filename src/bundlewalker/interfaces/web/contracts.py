# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Explicit, browser-safe contracts for the local web interface."""

import re
import unicodedata
from typing import Annotated, Final, Literal, Self
from urllib.parse import unquote_to_bytes, urlsplit

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
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_WINDOWS_ABSOLUTE_PATH_TEXT = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_WINDOWS_UNC_PATH_TEXT = re.compile(r"(?<![\\A-Za-z0-9])\\\\[^\\\s]+\\[^\\\s]+")
_UNIX_ABSOLUTE_PATH_TEXT = re.compile(r"(?<![:A-Za-z0-9])/(?!/)[^\s\"'<>`]+")
_MARKDOWN_LINK_DESTINATION = re.compile(
    r"(?P<prefix>(?<!!)\[[^\]\r\n]+\]\()"
    r"(?P<destination>[^)\r\n]+)"
    r"(?P<close>\))"
)
_MALFORMED_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HTTP_URL_TEXT = re.compile(r"(?<![A-Za-z0-9+.-])https?://[^\s\"'<>`]+", re.IGNORECASE)
_HTTP_SCHEME_TEXT = re.compile(r"(?<![A-Za-z0-9+.-])https?:", re.IGNORECASE)
_DANGEROUS_URI_TEXT = re.compile(
    r"(?<![A-Za-z0-9+.-])(?:data|file|javascript|vbscript):(?=\S)",
    re.IGNORECASE,
)
_SCHEME_SUFFIX_TEXT = re.compile(
    r"(?<![A-Za-z0-9+.-])"
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):"
    r"(?P<suffix>[^\s\"'<>`]*)",
)
_FILE_URI_PATH = re.compile(
    r"(?<![A-Za-z0-9+.-])file:(?:/{1,3}|%(?:25)*(?:2f|5c))",
    re.IGNORECASE,
)
_OKF_CONCEPT_CATEGORIES = frozenset({"sources", "topics", "entities", "syntheses"})
_MAX_PERCENT_DECODE_PASSES = 8

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

    @field_validator("summary")
    @classmethod
    def reject_summary_absolute_paths(cls, value: str) -> str:
        if _contains_absolute_path(value):
            raise ValueError("review metadata must not contain absolute paths")
        return value


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
        if _contains_absolute_path(value, allow_concept_markdown_links=True):
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
    segments = value.split("/")
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or _WINDOWS_DRIVE_PATH.match(value) is not None
        or _contains_control_character(value)
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        raise ValueError("web paths must be safe relative paths")


def _contains_absolute_path(
    value: str,
    *,
    allow_concept_markdown_links: bool = False,
) -> bool:
    if (
        _contains_file_uri_destination(value)
        or _DANGEROUS_URI_TEXT.search(value) is not None
        or _contains_unknown_path_scheme(value)
    ):
        return True
    inspected = _mask_safe_browser_destinations(
        value,
        allow_concept_markdown_links=allow_concept_markdown_links,
    )
    if (
        _HTTP_SCHEME_TEXT.search(inspected) is not None
        or _WINDOWS_ABSOLUTE_PATH_TEXT.search(inspected) is not None
        or _WINDOWS_UNC_PATH_TEXT.search(inspected) is not None
    ):
        return True
    return any(
        match.group().rstrip(".,);]}") != "/dev/null"
        for match in _UNIX_ABSOLUTE_PATH_TEXT.finditer(inspected)
    )


def _mask_safe_browser_destinations(
    value: str,
    *,
    allow_concept_markdown_links: bool,
) -> str:
    def replace(match: re.Match[str]) -> str:
        destination = match.group("destination")
        if not (
            _is_safe_http_url(destination)
            or (allow_concept_markdown_links and _is_safe_concept_destination(destination))
        ):
            return match.group()
        return f"{match.group('prefix')}bundlewalker-link{match.group('close')}"

    inspected = _MARKDOWN_LINK_DESTINATION.sub(replace, value)
    return _HTTP_URL_TEXT.sub(
        lambda match: "bundlewalker-link" if _is_safe_http_url(match.group()) else match.group(),
        inspected,
    )


def _contains_file_uri_destination(value: str) -> bool:
    return _FILE_URI_PATH.search(value) is not None or any(
        match.group("destination").casefold().startswith("file:")
        for match in _MARKDOWN_LINK_DESTINATION.finditer(value)
    )


def _contains_unknown_path_scheme(value: str) -> bool:
    for match in _SCHEME_SUFFIX_TEXT.finditer(value):
        if match.group("scheme").casefold() in {
            "data",
            "file",
            "http",
            "https",
            "javascript",
            "vbscript",
        }:
            continue
        suffix = match.group("suffix")
        decoded = _decode_percent_recursively(suffix) if "%" in suffix else suffix
        if decoded is None:
            return True
        if "/" in decoded or "\\" in decoded:
            return True
    return False


def _is_safe_http_url(value: str) -> bool:
    if (
        "\\" in value
        or _contains_control_character(value)
        or _MALFORMED_PERCENT_ESCAPE.search(value) is not None
    ):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
    ):
        return False

    decoded_netloc = _decode_percent_recursively(parsed.netloc)
    decoded_path = _decode_percent_recursively(parsed.path)
    decoded_query = _decode_percent_recursively(parsed.query)
    decoded_fragment = _decode_percent_recursively(parsed.fragment)
    if (
        decoded_netloc is None
        or decoded_path is None
        or decoded_query is None
        or decoded_fragment is None
    ):
        return False
    return not (
        "@" in decoded_netloc
        or "/" in decoded_netloc
        or "\\" in decoded_netloc
        or _contains_control_character(decoded_netloc)
        or "\\" in decoded_path
        or "\\" in decoded_query
        or "\\" in decoded_fragment
        or _contains_control_character(decoded_path)
        or _contains_control_character(decoded_query)
        or _contains_control_character(decoded_fragment)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    )


def _is_safe_concept_destination(destination: str) -> bool:
    if (
        not destination.startswith("/")
        or destination.startswith("//")
        or "\\" in destination
        or any(character.isspace() for character in destination)
        or _contains_control_character(destination)
        or _MALFORMED_PERCENT_ESCAPE.search(destination) is not None
    ):
        return False

    suffix_start = min(
        (index for marker in ("?", "#") if (index := destination.find(marker)) >= 0),
        default=len(destination),
    )
    raw_path = destination[:suffix_start]
    suffix = destination[suffix_start:]
    raw_segments = raw_path[1:].split("/")
    if len(raw_segments) < 2 or any(not segment for segment in raw_segments):
        return False

    decoded_segments: list[str] = []
    for segment in raw_segments:
        decoded = _decode_percent_recursively(segment)
        if decoded is None or _decoded_path_segment_is_unsafe(decoded):
            return False
        decoded_segments.append(decoded)
    decoded_suffix = _decode_percent_recursively(suffix)
    if decoded_suffix is None:
        return False

    if (
        "/" in decoded_suffix
        or "\\" in decoded_suffix
        or _contains_control_character(decoded_suffix)
    ):
        return False
    last_segment = decoded_segments[-1]
    return (
        decoded_segments[0] in _OKF_CONCEPT_CATEGORIES
        and last_segment.endswith(".md")
        and bool(last_segment[: -len(".md")])
    )


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _decoded_path_segment_is_unsafe(value: str) -> bool:
    return (
        value in {".", ".."} or "/" in value or "\\" in value or _contains_control_character(value)
    )


def _decode_percent_recursively(value: str) -> str | None:
    inspected = value
    for _ in range(_MAX_PERCENT_DECODE_PASSES):
        if _MALFORMED_PERCENT_ESCAPE.search(inspected) is not None:
            return None
        if "%" not in inspected:
            return inspected
        try:
            decoded = unquote_to_bytes(inspected).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if decoded == inspected:
            return inspected
        inspected = decoded
    return None if "%" in inspected else inspected
