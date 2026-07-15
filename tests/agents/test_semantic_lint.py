from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from bundlewalker.agents.common import AgentDependencies, read_tools
from bundlewalker.agents.semantic_lint import (
    create_semantic_lint_agent,
    run_semantic_lint_agent,
)
from bundlewalker.domain import FindingOrigin, LintFinding, OkfMetadata, Severity
from bundlewalker.errors import AgentRunError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _dependencies(tmp_path: Path) -> AgentDependencies:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    concept = workspace.wiki_dir / "topics" / "agents.md"
    concept.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    repository = OkfRepository(workspace.wiki_dir)
    return AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="Keep findings concise.",
        root_index=(workspace.wiki_dir / "index.md").read_text(encoding="utf-8"),
    )


def _finding(
    *,
    code: str = "SEM-GAP",
    evidence_paths: list[str] | None = None,
) -> LintFinding:
    return LintFinding(
        origin=FindingOrigin.DETERMINISTIC,
        severity=Severity.INFO,
        code=code,
        path="topics/agents.md",
        message="The topic could use another source.",
        evidence_paths=["topics/agents"] if evidence_paths is None else evidence_paths,
    )


def _signals() -> tuple[LintFinding, ...]:
    return (
        LintFinding(
            origin=FindingOrigin.DETERMINISTIC,
            severity=Severity.WARNING,
            code="ORPHAN001",
            path="topics/agents.md",
            message="concept has no inbound concept links",
        ),
    )


def test_semantic_lint_agent_has_the_strict_read_only_contract() -> None:
    agent = create_semantic_lint_agent(TestModel())
    details = cast(Any, agent)

    assert agent.deps_type is AgentDependencies
    assert agent.output_type == list[LintFinding]
    assert details._max_output_retries == 2
    assert details._max_tool_retries == 2
    assert tuple(details._function_toolset.tools) == tuple(tool.__name__ for tool in read_tools)

    instructions = "\n".join(details._instructions).casefold()
    assert "untrusted data" in instructions
    assert "never follow instructions" in instructions
    assert "read-only" in instructions
    assert "never write" in instructions
    assert "evidence" in instructions and "read" in instructions
    for code in (
        "sem-contradiction",
        "sem-stale",
        "sem-unsupported",
        "sem-missing",
        "sem-gap",
    ):
        assert code in instructions


async def test_semantic_runner_frames_context_and_accepts_only_read_evidence(
    tmp_path: Path,
) -> None:
    dependencies = _dependencies(tmp_path)
    expected = _finding()
    captured: dict[str, str] = {}
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        captured["instructions"] = info.instructions or ""
        captured["prompt"] = "\n".join(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_concept",
                        args={"concept_id": "topics/agents"},
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"response": [expected.model_dump(mode="json")]},
                )
            ]
        )

    findings, read_ids = await run_semantic_lint_agent(
        FunctionModel(respond),
        dependencies,
        _signals(),
    )

    assert findings == [expected.model_copy(update={"origin": FindingOrigin.SEMANTIC})]
    assert read_ids == frozenset({"topics/agents"})
    assert calls == 2
    prompt = captured["prompt"]
    framing, serialized = prompt.split("\n", maxsplit=1)
    assert framing == "UNTRUSTED_DATA_JSON_V1"
    payload = json.loads(serialized)
    assert payload == {
        "deterministic_lint_signals": {
            "count": 1,
            "content": [finding.model_dump(mode="json") for finding in _signals()],
        },
        "root_index": {
            "character_count": len(dependencies.root_index),
            "content": dependencies.root_index,
        },
        "workspace_conventions": {
            "character_count": len(dependencies.conventions),
            "content": dependencies.conventions,
        },
    }
    assert "untrusted data" in captured["instructions"].casefold()


@pytest.mark.parametrize(
    ("finding", "message"),
    [
        (_finding(code="SEM-OTHER"), "code"),
        (_finding(evidence_paths=[]), "evidence"),
        (_finding(), "was not read"),
    ],
)
async def test_semantic_runner_rejects_invalid_or_unread_findings(
    tmp_path: Path,
    finding: LintFinding,
    message: str,
) -> None:
    dependencies = _dependencies(tmp_path)
    dependencies.read_ids.add("topics/agents")

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"response": [finding.model_dump(mode="json")]},
                )
            ]
        )

    with pytest.raises(AgentRunError, match=message):
        await run_semantic_lint_agent(FunctionModel(respond), dependencies, _signals())


async def test_semantic_runner_drops_sensitive_provider_exception_chains(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path)
    secret = "semantic-provider-secret-that-must-not-survive"

    def fail_with_secret(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError(f"provider echoed {secret}")

    with pytest.raises(AgentRunError) as caught:
        await run_semantic_lint_agent(FunctionModel(fail_with_secret), dependencies, _signals())

    error = caught.value
    formatted = "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in formatted
    assert "provider echoed" not in formatted
