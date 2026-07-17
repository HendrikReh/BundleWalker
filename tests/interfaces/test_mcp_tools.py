import pytest
from pydantic import BaseModel, ValidationError

from bundlewalker.application import (
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
from bundlewalker.domain import MAX_CONCEPT_ID_CHARACTERS
from bundlewalker.interfaces.mcp_schemas import (
    MAX_MODEL_NAME_CHARACTERS,
    TOOL_SPECS,
    AskInput,
    EmptyInput,
    LintInput,
    PrepareIngestionInput,
    PrepareRefreshInput,
    PrepareSynthesisInput,
    ReviewIdInput,
    SearchInput,
)


def test_mcp_tool_specs_have_unique_names_and_closed_schemas() -> None:
    assert [spec.name for spec in TOOL_SPECS] == [
        "workspace_status",
        "search_concepts",
        "ask",
        "lint",
        "prepare_ingestion",
        "prepare_synthesis",
        "prepare_refresh",
        "get_pending_review",
        "apply_review",
        "discard_review",
    ]
    assert all(
        spec.input_model.model_json_schema()["additionalProperties"] is False for spec in TOOL_SPECS
    )


def test_model_backed_tool_annotations_are_open_world() -> None:
    by_name = {spec.name: spec for spec in TOOL_SPECS}
    assert by_name["ask"].annotations.openWorldHint is True
    assert by_name["lint"].annotations.openWorldHint is True
    assert by_name["prepare_ingestion"].annotations.openWorldHint is True
    assert by_name["workspace_status"].annotations.openWorldHint is False


def test_tool_specs_map_to_the_public_application_contracts() -> None:
    assert [(spec.input_model, spec.output_model) for spec in TOOL_SPECS] == [
        (EmptyInput, WorkspaceStatus),
        (SearchInput, ConceptSearchResult),
        (AskInput, AnswerResult),
        (LintInput, LintResult),
        (PrepareIngestionInput, IngestionResult),
        (PrepareSynthesisInput, SynthesisResult),
        (PrepareRefreshInput, RefreshResult),
        (EmptyInput, PendingReviewResult),
        (ReviewIdInput, MutationResult),
        (ReviewIdInput, MutationResult),
    ]
    assert all(spec.output_model.model_json_schema()["type"] == "object" for spec in TOOL_SPECS)


def test_tool_annotations_describe_reviewed_mutation_boundaries() -> None:
    by_name = {spec.name: spec for spec in TOOL_SPECS}
    for name in ("workspace_status", "search_concepts", "get_pending_review"):
        annotations = by_name[name].annotations
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.openWorldHint is False
        assert annotations.idempotentHint is True
    for name in ("ask", "lint"):
        annotations = by_name[name].annotations
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.openWorldHint is True
        assert annotations.idempotentHint is False
    for name in ("prepare_ingestion", "prepare_synthesis", "prepare_refresh"):
        annotations = by_name[name].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is False
        assert annotations.openWorldHint is True
        assert annotations.idempotentHint is False
    for name in ("apply_review", "discard_review"):
        annotations = by_name[name].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is True
        assert annotations.openWorldHint is False
        assert annotations.idempotentHint is False


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (EmptyInput, {"unexpected": True}),
        (SearchInput, {"query": "find", "limit": 11}),
        (AskInput, {"question": "q", "model": "m" * (MAX_MODEL_NAME_CHARACTERS + 1)}),
        (LintInput, {"model": ""}),
        (PrepareIngestionInput, {"source_name": "source.md", "content": "text", "path": "/tmp/x"}),
        (PrepareSynthesisInput, {"question": ""}),
        (
            PrepareRefreshInput,
            {"instruction": "refresh", "concept_id": "c" * (MAX_CONCEPT_ID_CHARACTERS + 1)},
        ),
        (ReviewIdInput, {"review_id": "A" * 32}),
    ],
)
def test_mcp_inputs_reject_out_of_bound_or_unapproved_fields(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
