from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from bundlewalker.agents.common import AgentDependencies, read_concept
from bundlewalker.agents.query import AgentModel as QueryAgentModel
from bundlewalker.agents.semantic_lint import AgentModel as LintAgentModel
from bundlewalker.application import (
    AnswerResult,
    ApplicationDependencies,
    ApplicationError,
    ApplicationErrorCode,
    ConceptSearchResult,
    IngestionResult,
    LintResult,
    MutationResult,
    PendingReviewResult,
    RefreshResult,
    SynthesisResult,
    WorkspaceApplication,
    WorkspaceStatus,
)
from bundlewalker.domain import (
    MAX_CONCEPT_ID_CHARACTERS,
    Citation,
    CitedAnswer,
    FindingOrigin,
    LintFinding,
    OkfMetadata,
    Severity,
)
from bundlewalker.interfaces.mcp import create_mcp_server
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
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    path = workspace.wiki_dir / "topics" / "agents.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return workspace


def _answer() -> CitedAnswer:
    return CitedAnswer(
        title="Agent tools",
        body="# Answer\n\nAgents can use tools [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


async def _query_runner(
    model: QueryAgentModel,
    dependencies: AgentDependencies,
    question: str,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert question == "What do agents use?"
    result = read_concept(
        RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
        "topics/agents",
    )
    assert "error" not in result
    return _answer(), frozenset({"topics/agents"})


async def _semantic_lint_runner(
    model: LintAgentModel,
    dependencies: AgentDependencies,
    _deterministic_findings: tuple[LintFinding, ...],
) -> tuple[list[LintFinding], frozenset[str]]:
    assert model == "test:model"
    result = read_concept(
        RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
        "topics/agents",
    )
    assert "error" not in result
    return (
        [
            LintFinding(
                origin=FindingOrigin.SEMANTIC,
                severity=Severity.INFO,
                code="SEM-GAP",
                message="The topic could include more context.",
                path="topics/agents.md",
                evidence_paths=["topics/agents"],
            )
        ],
        frozenset({"topics/agents"}),
    )


@pytest.fixture
def application(tmp_path: Path) -> WorkspaceApplication:
    return WorkspaceApplication(
        _workspace(tmp_path),
        ApplicationDependencies(
            environment={},
            query_runner=_query_runner,
            semantic_lint_runner=_semantic_lint_runner,
        ),
    )


@pytest.fixture
def application_with_pending_review(tmp_path: Path) -> WorkspaceApplication:
    workspace = _workspace(tmp_path)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(answer=_answer(), read_ids=frozenset({"topics/agents"})),
        occurred_at=NOW,
    )
    return WorkspaceApplication(workspace)


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


async def test_mcp_lists_exact_static_tool_definitions(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()

    assert listed.tools == [
        types.Tool(
            name=spec.name,
            title=spec.title,
            description=spec.description,
            inputSchema=spec.input_model.model_json_schema(),
            outputSchema=spec.output_model.model_json_schema(),
            annotations=spec.annotations,
        )
        for spec in TOOL_SPECS
    ]


async def test_workspace_status_tool_returns_structured_and_text_content(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("workspace_status", {})

    assert result.isError is False
    assert result.structuredContent is not None
    validated = WorkspaceStatus.model_validate(result.structuredContent)
    assert validated.display_name == application.workspace.root.name
    assert isinstance(result.content[0], types.TextContent)
    assert validated.display_name in result.content[0].text
    assert str(application.workspace.root) not in result.content[0].text


async def test_search_tool_returns_validated_results(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "search_concepts",
            {"query": "agents", "concept_type": "Topic", "limit": 1},
        )

    assert result.isError is False
    assert result.structuredContent is not None
    validated = ConceptSearchResult.model_validate(result.structuredContent)
    assert [item.concept_id for item in validated.items] == ["topics/agents"]
    assert isinstance(result.content[0], types.TextContent)
    assert "topics/agents" in result.content[0].text


async def test_ask_tool_uses_fake_runner_and_returns_rendered_citations(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "ask",
            {"question": "What do agents use?", "model": "test:model"},
        )

    assert result.isError is False
    assert result.structuredContent is not None
    validated = AnswerResult.model_validate(result.structuredContent)
    assert validated.answer == _answer()
    assert "[Agents](/topics/agents.md)" in validated.markdown
    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == validated.markdown


@pytest.mark.parametrize("semantic", [False, True], ids=["deterministic", "semantic"])
async def test_lint_tool_returns_one_bounded_line_per_finding(
    application: WorkspaceApplication,
    semantic: bool,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "lint",
            {"semantic": semantic, "model": "test:model" if semantic else None},
        )

    assert result.isError is False
    assert result.structuredContent is not None
    validated = LintResult.model_validate(result.structuredContent)
    if semantic:
        assert any(finding.code == "SEM-GAP" for finding in validated.findings)
    assert isinstance(result.content[0], types.TextContent)
    lines = result.content[0].text.splitlines()
    assert len(lines) == max(1, len(validated.findings))
    assert all(len(line) <= 1_024 for line in lines)


async def test_pending_review_tool_wraps_optional_value_and_preserves_exact_diff(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("get_pending_review", {})

    assert result.isError is False
    assert result.structuredContent is not None
    validated = PendingReviewResult.model_validate(result.structuredContent)
    assert validated.review == expected
    assert isinstance(result.content[0], types.TextContent)
    assert expected.diff in result.content[0].text


async def test_pending_review_tool_returns_object_root_when_none_is_pending(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("get_pending_review", {})

    assert result.isError is False
    assert result.structuredContent == {"review": None}
    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "No pending review."


async def test_invalid_search_is_a_tool_execution_error(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("search_concepts", {"query": "", "limit": 10})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"] == {
        "code": "invalid_input",
        "message": "invalid tool input",
        "retryable": False,
        "review_id": None,
    }


async def test_unknown_and_undispatched_tools_return_bounded_execution_errors(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        unknown = await session.call_tool("not_a_bundlewalker_tool", {"secret": "/tmp/private"})
        undispatched = await session.call_tool(
            "prepare_ingestion",
            {"source_name": "notes.txt", "content": "text"},
        )

    for result in (unknown, undispatched):
        assert result.isError is True
        assert result.structuredContent is not None
        assert result.structuredContent["error"]["code"] == "invalid_input"
        assert isinstance(result.content[0], types.TextContent)
        assert len(result.content[0].text) < 256
        assert "/tmp/private" not in result.content[0].text


async def test_application_error_is_returned_as_a_tool_execution_error(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_status() -> WorkspaceStatus:
        raise ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            "workspace configuration is invalid",
        )

    monkeypatch.setattr(application, "status", fail_status)
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("workspace_status", {})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "configuration_error"
    assert result.content == [
        types.TextContent(type="text", text="workspace configuration is invalid")
    ]


async def test_unexpected_exception_is_logged_and_returns_no_private_detail(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_detail = f"unexpected failure at {application.workspace.root / 'private.txt'}"

    async def fail_status() -> WorkspaceStatus:
        raise RuntimeError(private_detail)

    monkeypatch.setattr(application, "status", fail_status)
    server = create_mcp_server(application)

    with caplog.at_level(logging.ERROR, logger="bundlewalker.interfaces.mcp_tools"):
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("workspace_status", {})

    assert private_detail in caplog.text
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"] == {
        "code": "workspace_error",
        "message": "BundleWalker operation failed",
        "retryable": False,
        "review_id": None,
    }
    assert application.workspace.root.as_posix() not in result.model_dump_json()
