from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from mcp import types
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl, BaseModel, ValidationError
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
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    FindingOrigin,
    LintFinding,
    OkfDocument,
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
from bundlewalker.workspace import RawSource, Workspace, initialize_workspace

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


def _ingestion_change_set(source: RawSource) -> ChangeSet:
    return ChangeSet(
        summary="Integrated notes.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Notes",
                description="Notes from the incoming source.",
                tags=["notes"],
                body="# Notes\n\nThe source contains evidence [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=1,
                    )
                ],
            )
        ],
    )


async def _ingestion_runner(
    model: QueryAgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    assert model == "test:model"
    return _ingestion_change_set(source), frozenset()


def _write_refresh_target(workspace: Workspace) -> None:
    path = workspace.wiki_dir / "syntheses" / "current-agent-framework.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_document(
            OkfMetadata(
                type="Synthesis",
                title="Current Agent Framework",
                description="A maintained decision framework.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Current answer\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)


async def _current_refresh_runner(
    model: QueryAgentModel,
    dependencies: AgentDependencies,
    instruction: str,
    target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert instruction == "Refresh this answer"
    assert target.concept_id == "syntheses/current-agent-framework"
    dependencies.read_ids.add("topics/agents")
    return (
        CitedAnswer(
            title="Current Agent Framework",
            body="# Current answer\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        frozenset({"topics/agents"}),
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


async def _cancel_request(session: Any, request_id: int | str) -> None:
    await session.send_notification(
        types.ClientNotification(
            types.CancelledNotification(
                params=types.CancelledNotificationParams(
                    requestId=request_id,
                    reason="test cancellation",
                )
            )
        )
    )


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
            ingestion_runner=_ingestion_runner,
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


async def test_prepare_then_apply_uses_two_explicit_tool_calls(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        prepared = await session.call_tool(
            "prepare_ingestion",
            {
                "source_name": "notes.txt",
                "content": "evidence\n",
                "model": "test:model",
            },
        )
        assert prepared.structuredContent is not None
        validated = IngestionResult.model_validate(prepared.structuredContent)
        assert validated.review is not None
        review_id = validated.review.review_id
        assert _tree_bytes(application.workspace.raw_dir) == {}
        applied = await session.call_tool("apply_review", {"review_id": review_id})

    assert prepared.isError is False
    assert validated.review.diff
    assert isinstance(prepared.content[0], types.TextContent)
    assert review_id in prepared.content[0].text
    assert validated.review.summary in prepared.content[0].text
    assert validated.review.diff in prepared.content[0].text
    assert "bundlewalker://review/pending" in prepared.content[0].text
    assert applied.isError is False
    assert applied.structuredContent is not None
    assert MutationResult.model_validate(applied.structuredContent) == MutationResult(
        review_id=review_id,
        status="applied",
    )
    assert _tree_bytes(application.workspace.raw_dir)


async def test_mcp_ingestion_has_no_path_argument(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_ingestion",
            {
                "source_name": "notes.txt",
                "content": "text\n",
                "path": "/tmp/secret",
            },
        )

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "invalid_input"
    assert "/tmp/secret" not in result.model_dump_json()
    assert await application.get_pending_review() is None


async def test_prepared_review_survives_a_new_in_memory_server_session(
    application: WorkspaceApplication,
) -> None:
    first_server = create_mcp_server(application)
    async with create_connected_server_and_client_session(first_server) as session:
        prepared = await session.call_tool(
            "prepare_ingestion",
            {
                "source_name": "notes.txt",
                "content": "evidence\n",
                "model": "test:model",
            },
        )

    assert prepared.structuredContent is not None
    first = IngestionResult.model_validate(prepared.structuredContent)
    assert first.review is not None
    restarted = WorkspaceApplication(application.workspace)
    second_server = create_mcp_server(restarted)
    async with create_connected_server_and_client_session(second_server) as session:
        loaded = await session.call_tool("get_pending_review", {})

    assert loaded.structuredContent is not None
    pending = PendingReviewResult.model_validate(loaded.structuredContent)
    assert pending.review is not None
    assert pending.review.review_id == first.review.review_id
    assert pending.review.diff == first.review.diff


async def test_discard_review_requires_a_second_explicit_call(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        discarded = await session.call_tool(
            "discard_review",
            {"review_id": expected.review_id},
        )
        loaded = await session.call_tool("get_pending_review", {})

    assert discarded.isError is False
    assert discarded.structuredContent is not None
    assert MutationResult.model_validate(discarded.structuredContent).status == "discarded"
    assert loaded.structuredContent == {"review": None}


async def test_wrong_review_id_does_not_resolve_current_review(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("apply_review", {"review_id": "0" * 32})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "review_id_mismatch"
    assert await application_with_pending_review.get_pending_review() == expected


async def test_stale_review_cannot_be_applied(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    (application_with_pending_review.workspace.wiki_dir / "external.md").write_text(
        "external edit\n",
        encoding="utf-8",
    )
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("apply_review", {"review_id": expected.review_id})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "review_stale"
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None
    assert pending.review_id == expected.review_id


async def test_prepare_synthesis_uses_exactly_one_model_call(tmp_path: Path) -> None:
    calls = 0

    async def runner(
        model: QueryAgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return await _query_runner(model, dependencies, question)

    application = WorkspaceApplication(
        _workspace(tmp_path),
        ApplicationDependencies(environment={}, query_runner=runner, clock=lambda: NOW),
    )
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_synthesis",
            {"question": "What do agents use?", "model": "test:model"},
        )

    assert result.isError is False
    assert result.structuredContent is not None
    validated = SynthesisResult.model_validate(result.structuredContent)
    assert calls == 1
    assert validated.answer.answer == _answer()
    assert isinstance(result.content[0], types.TextContent)
    assert validated.review.review_id in result.content[0].text
    assert validated.review.summary in result.content[0].text
    assert validated.review.diff in result.content[0].text
    assert validated.review.resource_uri in result.content[0].text


async def test_prepare_refresh_reports_unchanged_without_a_review(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_refresh_target(workspace)
    application = WorkspaceApplication(
        workspace,
        ApplicationDependencies(
            environment={},
            refresh_runner=_current_refresh_runner,
            clock=lambda: NOW,
        ),
    )
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_refresh",
            {
                "instruction": "Refresh this answer",
                "concept_id": "syntheses/current-agent-framework",
                "model": "test:model",
            },
        )

    assert result.isError is False
    assert result.structuredContent is not None
    validated = RefreshResult.model_validate(result.structuredContent)
    assert validated.status == "current"
    assert validated.review is None
    assert await application.get_pending_review() is None


async def test_pending_review_gate_runs_before_provider_invocation(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    calls = 0

    async def must_not_run(
        _model: QueryAgentModel,
        _dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("pending synthesis invoked provider")

    blocked = WorkspaceApplication(
        application_with_pending_review.workspace,
        ApplicationDependencies(environment={}, query_runner=must_not_run),
    )
    server = create_mcp_server(blocked)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_synthesis",
            {"question": "Question", "model": "test:model"},
        )

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "review_pending"
    assert calls == 0


async def test_prepare_reports_protocol_progress_with_request_token(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str | int, float, float | None, str | None]] = []
    callbacks: list[tuple[float, float | None, str | None]] = []

    from mcp.server.session import ServerSession

    original = ServerSession.send_progress_notification

    async def capture_progress(
        self: ServerSession,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        notifications.append((progress_token, progress, total, message))
        await original(
            self,
            progress_token,
            progress,
            total,
            message,
            related_request_id,
        )

    async def progress_callback(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        callbacks.append((progress, total, message))

    monkeypatch.setattr(ServerSession, "send_progress_notification", capture_progress)
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        request_id = cast(Any, session)._request_id
        result = await session.call_tool(
            "prepare_ingestion",
            {
                "source_name": "notes.txt",
                "content": "evidence\n",
                "model": "test:model",
            },
            progress_callback=progress_callback,
        )

    assert result.isError is False
    assert notifications == [
        (request_id, 0.0, 1.0, "Preparing ingestion review"),
        (request_id, 1.0, 1.0, "Prepared ingestion review"),
    ]
    assert callbacks == [
        (0.0, 1.0, "Preparing ingestion review"),
        (1.0, 1.0, "Prepared ingestion review"),
    ]


async def test_final_progress_failure_does_not_hide_successful_durable_review(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from mcp.server.session import ServerSession

    original = ServerSession.send_progress_notification

    async def fail_final_progress(
        self: ServerSession,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        if progress == 1.0:
            raise RuntimeError("final progress transport failed")
        await original(
            self,
            progress_token,
            progress,
            total,
            message,
            related_request_id,
        )

    async def ignore_progress(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        del progress, total, message
        return None

    monkeypatch.setattr(ServerSession, "send_progress_notification", fail_final_progress)
    server = create_mcp_server(application)

    with caplog.at_level(logging.ERROR, logger="bundlewalker.interfaces.mcp_tools"):
        async with create_connected_server_and_client_session(server) as session:
            prepared = await session.call_tool(
                "prepare_ingestion",
                {
                    "source_name": "notes.txt",
                    "content": "evidence\n",
                    "model": "test:model",
                },
                progress_callback=ignore_progress,
            )
            loaded = await session.call_tool("get_pending_review", {})

    assert prepared.isError is False
    assert prepared.structuredContent is not None
    result = IngestionResult.model_validate(prepared.structuredContent)
    assert result.review is not None
    assert loaded.structuredContent is not None
    durable = PendingReviewResult.model_validate(loaded.structuredContent).review
    assert durable is not None
    assert result.review.review_id == durable.review_id
    assert result.review.diff == durable.diff
    assert "RuntimeError: final progress transport failed" in caplog.text
    assert "final progress" in caplog.text


async def test_cancellation_before_persistence_leaves_no_review(tmp_path: Path) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_runner(
        _model: QueryAgentModel,
        _dependencies: AgentDependencies,
        _source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    application = WorkspaceApplication(
        _workspace(tmp_path),
        ApplicationDependencies(environment={}, ingestion_runner=blocking_runner),
    )
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        request_id = cast(Any, session)._request_id
        call = asyncio.create_task(
            session.call_tool(
                "prepare_ingestion",
                {
                    "source_name": "notes.txt",
                    "content": "evidence\n",
                    "model": "test:model",
                },
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await _cancel_request(session, request_id)
        with pytest.raises(McpError, match="Request cancelled"):
            await call
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    assert await application.get_pending_review() is None
    assert _tree_bytes(application.workspace.raw_dir) == {}


async def test_cancellation_immediately_after_persistence_leaves_review_discoverable(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_progress_started = asyncio.Event()
    cancelled = asyncio.Event()

    from mcp.server.session import ServerSession

    original = ServerSession.send_progress_notification

    async def block_final_progress(
        self: ServerSession,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        if progress == 0.0:
            await original(
                self,
                progress_token,
                progress,
                total,
                message,
                related_request_id,
            )
            return
        final_progress_started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async def ignore_progress(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        del progress, total, message
        return None

    monkeypatch.setattr(ServerSession, "send_progress_notification", block_final_progress)
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        request_id = cast(Any, session)._request_id
        call = asyncio.create_task(
            session.call_tool(
                "prepare_ingestion",
                {
                    "source_name": "notes.txt",
                    "content": "evidence\n",
                    "model": "test:model",
                },
                progress_callback=ignore_progress,
            )
        )
        await asyncio.wait_for(final_progress_started.wait(), timeout=1)
        expected = await application.get_pending_review()
        assert expected is not None
        await _cancel_request(session, request_id)
        with pytest.raises(McpError, match="Request cancelled"):
            await call
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        loaded = await session.call_tool("get_pending_review", {})
        resource = await session.read_resource(AnyUrl(expected.resource_uri))

    assert loaded.structuredContent is not None
    review = PendingReviewResult.model_validate(loaded.structuredContent).review
    assert review is not None
    assert review.review_id == expected.review_id
    assert review.diff == expected.diff
    content = resource.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert expected.review_id in content.text
    assert expected.diff in content.text


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


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("lint", {"semantic": "false"}),
        ("search_concepts", {"query": "agents", "limit": "1"}),
    ],
    ids=["boolean-string", "integer-string"],
)
async def test_schema_invalid_json_scalar_is_a_tool_execution_error(
    application: WorkspaceApplication,
    name: str,
    arguments: dict[str, object],
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(name, arguments)

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"] == {
        "code": "invalid_input",
        "message": "invalid tool input",
        "retryable": False,
        "review_id": None,
    }


async def test_unknown_tool_returns_a_bounded_execution_error(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("not_a_bundlewalker_tool", {"secret": "/tmp/private"})

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


async def test_facade_validation_error_is_logged_as_unexpected_and_redacted(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail_status() -> WorkspaceStatus:
        return WorkspaceStatus.model_validate(
            {"display_name": str(application.workspace.root / "private.txt")}
        )

    monkeypatch.setattr(application, "status", fail_status)
    server = create_mcp_server(application)

    with caplog.at_level(logging.ERROR, logger="bundlewalker.interfaces.mcp_tools"):
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("workspace_status", {})

    assert "ValidationError" in caplog.text
    assert "private.txt" in caplog.text
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"] == {
        "code": "workspace_error",
        "message": "BundleWalker operation failed",
        "retryable": False,
        "review_id": None,
    }
    assert application.workspace.root.as_posix() not in result.model_dump_json()


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
