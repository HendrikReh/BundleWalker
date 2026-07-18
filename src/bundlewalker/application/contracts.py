# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adapter-neutral, serialized application-boundary contracts."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bundlewalker.domain import CitedAnswer, LintFinding
from bundlewalker.transactions import ReviewKind, ReviewStatus

MAX_QUESTION_CHARACTERS = 20_000
MAX_SEARCH_CHARACTERS = 2_000
MAX_SOURCE_NAME_CHARACTERS = 255
MAX_INLINE_SOURCE_CHARACTERS = 1_000_000
MAX_CONCEPT_PAGE_SIZE = 100


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
