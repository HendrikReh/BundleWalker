# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static, transport-independent MCP tool schemas."""

from dataclasses import dataclass

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from bundlewalker.application import (
    MAX_INLINE_SOURCE_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    MAX_SEARCH_CHARACTERS,
    MAX_SOURCE_NAME_CHARACTERS,
    AnswerResult,
    ConceptSearchResult,
    IngestionResult,
    LintResult,
    MutationResult,
    PendingReviewResult,
    RefreshResult,
    SynthesisResult,
    WorkspaceStatus,
)
from bundlewalker.domain import MAX_CONCEPT_ID_CHARACTERS, ConceptType

MAX_MODEL_NAME_CHARACTERS = 255


class EmptyInput(BaseModel):
    """A tool input that intentionally accepts no fields."""

    model_config = ConfigDict(extra="forbid")


class SearchInput(BaseModel):
    """A bounded lexical concept search request."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_SEARCH_CHARACTERS)
    concept_type: ConceptType | None = None
    limit: int = Field(default=10, ge=1, le=10)


class AskInput(BaseModel):
    """A model-backed question request."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class LintInput(BaseModel):
    """A deterministic or model-assisted lint request."""

    model_config = ConfigDict(extra="forbid")

    semantic: bool = False
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class PrepareIngestionInput(BaseModel):
    """An inline-source ingestion preparation request."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1, max_length=MAX_SOURCE_NAME_CHARACTERS)
    content: str = Field(max_length=MAX_INLINE_SOURCE_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class PrepareSynthesisInput(AskInput):
    """A question whose answer is prepared as a Synthesis review."""


class PrepareRefreshInput(BaseModel):
    """A bounded Synthesis refresh preparation request."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    concept_id: str = Field(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class ReviewIdInput(BaseModel):
    """An opaque durable review identifier."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(pattern=r"^[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Static metadata shared by MCP server registration and dispatch."""

    name: str
    title: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    annotations: ToolAnnotations


_READ_ONLY_CLOSED_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
_PREPARE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
_RESOLVE_REVIEW = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="workspace_status",
        title="Workspace Status",
        description="Inspect the configured workspace and its pending review, if any.",
        input_model=EmptyInput,
        output_model=WorkspaceStatus,
        annotations=_READ_ONLY_CLOSED_WORLD,
    ),
    ToolSpec(
        name="search_concepts",
        title="Search Concepts",
        description="Search concepts in the configured workspace by bounded lexical query.",
        input_model=SearchInput,
        output_model=ConceptSearchResult,
        annotations=_READ_ONLY_CLOSED_WORLD,
    ),
    ToolSpec(
        name="ask",
        title="Ask BundleWalker",
        description="Answer a question from workspace knowledge with cited Markdown.",
        input_model=AskInput,
        output_model=AnswerResult,
        annotations=_READ_ONLY_OPEN_WORLD,
    ),
    ToolSpec(
        name="lint",
        title="Lint Workspace",
        description="Check workspace health, optionally with model-assisted advisories.",
        input_model=LintInput,
        output_model=LintResult,
        annotations=_READ_ONLY_OPEN_WORLD,
    ),
    ToolSpec(
        name="prepare_ingestion",
        title="Prepare Ingestion",
        description="Prepare an inline source for review without changing live workspace content.",
        input_model=PrepareIngestionInput,
        output_model=IngestionResult,
        annotations=_PREPARE,
    ),
    ToolSpec(
        name="prepare_synthesis",
        title="Prepare Synthesis",
        description="Prepare a cited Synthesis answer for review without applying it.",
        input_model=PrepareSynthesisInput,
        output_model=SynthesisResult,
        annotations=_PREPARE,
    ),
    ToolSpec(
        name="prepare_refresh",
        title="Prepare Refresh",
        description="Prepare a Synthesis refresh for review without applying it.",
        input_model=PrepareRefreshInput,
        output_model=RefreshResult,
        annotations=_PREPARE,
    ),
    ToolSpec(
        name="get_pending_review",
        title="Get Pending Review",
        description="Inspect the single pending workspace review, if one exists.",
        input_model=EmptyInput,
        output_model=PendingReviewResult,
        annotations=_READ_ONLY_CLOSED_WORLD,
    ),
    ToolSpec(
        name="apply_review",
        title="Apply Review",
        description="Apply the exact current review after durable state revalidation.",
        input_model=ReviewIdInput,
        output_model=MutationResult,
        annotations=_RESOLVE_REVIEW,
    ),
    ToolSpec(
        name="discard_review",
        title="Discard Review",
        description="Discard the exact current review without applying its changes.",
        input_model=ReviewIdInput,
        output_model=MutationResult,
        annotations=_RESOLVE_REVIEW,
    ),
)
