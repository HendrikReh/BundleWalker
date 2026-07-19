# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adapter-neutral, serialized application-boundary contracts."""

import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from bundlewalker.compatibility import CompatibilityStatus
from bundlewalker.domain import CitedAnswer, LintFinding
from bundlewalker.transactions import ReviewKind, ReviewStatus

MAX_QUESTION_CHARACTERS = 20_000
MAX_SEARCH_CHARACTERS = 2_000
MAX_SOURCE_NAME_CHARACTERS = 255
MAX_INLINE_SOURCE_CHARACTERS = 1_000_000
MAX_CONCEPT_PAGE_SIZE = 100
MAX_DIAGNOSTIC_REMEDIATION_CHARACTERS = 300


class DiagnosticSeverity(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAILURE = "failure"


class DiagnosticCategory(StrEnum):
    RUNTIME = "runtime"
    WORKSPACE = "workspace"
    CONFIGURATION = "configuration"
    TRANSACTIONS = "transactions"
    MCP = "mcp"
    STORAGE = "storage"


DIAGNOSTIC_CHECK_CATALOG: tuple[tuple[str, DiagnosticCategory], ...] = (
    ("runtime.bundlewalker", DiagnosticCategory.RUNTIME),
    ("runtime.python", DiagnosticCategory.RUNTIME),
    ("runtime.platform", DiagnosticCategory.RUNTIME),
    ("workspace.discovery", DiagnosticCategory.WORKSPACE),
    ("workspace.configuration", DiagnosticCategory.WORKSPACE),
    ("workspace.compatibility", DiagnosticCategory.WORKSPACE),
    ("workspace.structure", DiagnosticCategory.WORKSPACE),
    ("workspace.permissions", DiagnosticCategory.WORKSPACE),
    ("configuration.model", DiagnosticCategory.CONFIGURATION),
    ("configuration.credential", DiagnosticCategory.CONFIGURATION),
    ("transactions.state", DiagnosticCategory.TRANSACTIONS),
    ("mcp.package", DiagnosticCategory.MCP),
    ("mcp.entrypoint", DiagnosticCategory.MCP),
    ("storage.disk", DiagnosticCategory.STORAGE),
)


def _single_line(value: str) -> str:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("diagnostic text must be one printable line")
    return value


class DiagnosticCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)+$", max_length=80)
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    summary: str = Field(min_length=1, max_length=300)
    remediation: tuple[
        Annotated[str, Field(max_length=MAX_DIAGNOSTIC_REMEDIATION_CHARACTERS)], ...
    ] = Field(default=(), max_length=5)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _single_line(value)

    @field_validator("remediation")
    @classmethod
    def validate_remediation(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_single_line(value) for value in values)


class DiagnosticCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failures: int = Field(ge=0)


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    overall: DiagnosticSeverity
    bundlewalker_version: str = Field(min_length=1, max_length=80)
    python_version: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=40)
    counts: DiagnosticCounts
    checks: tuple[DiagnosticCheck, ...]

    @model_validator(mode="after")
    def validate_catalog_and_summary(self) -> Self:
        actual_catalog = tuple((check.code, check.category) for check in self.checks)
        if actual_catalog != DIAGNOSTIC_CHECK_CATALOG:
            raise ValueError("diagnostic checks must match the stable catalog")
        expected = DiagnosticCounts(
            passed=sum(check.severity is DiagnosticSeverity.PASS for check in self.checks),
            warnings=sum(check.severity is DiagnosticSeverity.WARNING for check in self.checks),
            failures=sum(check.severity is DiagnosticSeverity.FAILURE for check in self.checks),
        )
        if self.counts != expected:
            raise ValueError("diagnostic counts do not match checks")
        expected_overall = (
            DiagnosticSeverity.FAILURE
            if expected.failures
            else DiagnosticSeverity.WARNING
            if expected.warnings
            else DiagnosticSeverity.PASS
        )
        if self.overall is not expected_overall:
            raise ValueError("diagnostic overall severity does not match checks")
        return self


class SupportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    result: DiagnosticResult


class InlineSource(BaseModel):
    """A caller-provided source that has no filesystem identity."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=MAX_SOURCE_NAME_CHARACTERS)
    content: str = Field(max_length=MAX_INLINE_SOURCE_CHARACTERS)


class ReviewResult(BaseModel):
    """The serializable view of a pending or stale transaction review."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=32, max_length=32)
    kind: ReviewKind
    status: ReviewStatus
    summary: str
    diff: str
    changed_paths: tuple[str, ...]
    created_at: datetime
    resource_uri: str


class PendingReviewSummary(BaseModel):
    """The compact review view embedded in workspace status."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=32, max_length=32)
    kind: ReviewKind
    status: ReviewStatus
    summary: str


class PendingReviewResult(BaseModel):
    """The optional currently pending review."""

    model_config = ConfigDict(extra="forbid")

    review: ReviewResult | None


class MutationResult(BaseModel):
    """A review mutation outcome."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: Literal["applied", "discarded"]


class WorkspaceStatus(BaseModel):
    """The serialized state of a configured knowledge workspace."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    config_version: int
    concept_counts: dict[str, int]
    pending_review: PendingReviewSummary | None


class ConceptSummaryResult(BaseModel):
    """A compact concept representation for lists and search results."""

    model_config = ConfigDict(extra="forbid")

    concept_id: str
    type: str
    title: str
    description: str
    tags: tuple[str, ...]
    resource_uri: str


class ConceptContent(ConceptSummaryResult):
    """A complete serialized concept document."""

    model_config = ConfigDict(extra="forbid")

    markdown: str
    digest: str


class ConceptPage(BaseModel):
    """A bounded page of concepts."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[ConceptSummaryResult, ...]
    next_cursor: str | None


class ConceptSearchResult(BaseModel):
    """Concept search output."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[ConceptSummaryResult, ...]


class AnswerResult(BaseModel):
    """A validated cited answer and its rendered Markdown representation."""

    model_config = ConfigDict(extra="forbid")

    answer: CitedAnswer
    markdown: str


class LintResult(BaseModel):
    """Deterministic and model-assisted lint findings."""

    model_config = ConfigDict(extra="forbid")

    findings: tuple[LintFinding, ...]
    deterministic_has_errors: bool


class IngestionResult(BaseModel):
    """The duplicate or review-pending result of an ingestion operation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["duplicate", "pending"]
    review: ReviewResult | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending ingestion must contain exactly one review")
        return self


class SynthesisResult(BaseModel):
    """A synthesis answer paired with its mandatory pending review."""

    model_config = ConfigDict(extra="forbid")

    answer: AnswerResult
    review: ReviewResult


class RefreshResult(BaseModel):
    """The current or review-pending result of a refresh operation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["current", "pending"]
    concept_id: str
    answer: AnswerResult
    review: ReviewResult | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending refresh must contain exactly one review")
        return self


class CompatibilityResult(BaseModel):
    """A read-only workspace-format compatibility inspection."""

    model_config = ConfigDict(extra="forbid")

    installed_version: str
    workspace_path: str
    workspace_format: int
    compatibility: CompatibilityStatus
    readable: bool
    writable: bool
    upgrade_available: bool


class BackupResult(BaseModel):
    """The serializable identity and size of a verified workspace backup."""

    model_config = ConfigDict(extra="forbid")

    archive_path: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    workspace_format: int
    file_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


class RestoreResult(BaseModel):
    """The serializable identity and size of a verified restored workspace."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_format: int
    file_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


class UpgradeResult(BaseModel):
    """The outcome of an explicit current or migrated workspace upgrade."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["current", "upgraded"]
    workspace_path: str
    source_version: int
    target_version: int
    backup: BackupResult | None
