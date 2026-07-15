from __future__ import annotations

from pathlib import Path
from typing import Any, cast

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
from bundlewalker.agents.ingest import create_ingestion_agent, run_ingestion_agent
from bundlewalker.domain import ChangeOperation, ChangeSet, ConceptType, DraftConcept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.workspace import discover_workspace, initialize_workspace, load_raw_source


def _dependencies(tmp_path: Path) -> AgentDependencies:
    workspace = initialize_workspace(tmp_path / "knowledge")
    repository = OkfRepository(workspace.wiki_dir)
    return AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="Keep claims concise.",
        root_index="# Knowledge Index\n",
    )


def test_ingestion_agent_has_the_strict_read_only_contract() -> None:
    agent = create_ingestion_agent(TestModel())
    details = cast(Any, agent)

    assert agent.deps_type is AgentDependencies
    assert agent.output_type is ChangeSet
    assert details._max_output_retries == 2
    assert details._max_tool_retries == 2
    assert tuple(details._function_toolset.tools) == tuple(tool.__name__ for tool in read_tools)

    instructions = "\n".join(details._instructions).casefold()
    assert "untrusted data" in instructions
    assert "never follow instructions" in instructions
    assert "exactly one source" in instructions
    assert "source, topic, and entity" in instructions
    assert "synthesis" in instructions and "never" in instructions
    assert "uncertainty" in instructions
    assert "contradiction" in instructions
    assert "numbered" in instructions and "line" in instructions


async def test_ingestion_runner_delimits_context_and_numbers_source_lines(
    tmp_path: Path,
) -> None:
    dependencies = _dependencies(tmp_path)
    input_path = tmp_path / "notes.txt"
    input_path.write_bytes(b"alpha\r\nbeta\n")
    source = load_raw_source(input_path, discover_workspace(dependencies.repository.root))
    change_set = ChangeSet(
        summary="Integrated notes.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Notes",
                description="Source notes.",
                body="# Notes\n",
            )
        ],
    )
    captured: dict[str, str] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        captured["instructions"] = info.instructions or ""
        captured["prompt"] = "\n".join(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=change_set.model_dump(mode="json"),
                )
            ]
        )

    output, read_ids = await run_ingestion_agent(FunctionModel(respond), dependencies, source)

    assert output == change_set
    assert read_ids == frozenset()
    prompt = captured["prompt"]
    assert '<workspace-conventions trust="untrusted-data">' in prompt
    assert "Keep claims concise." in prompt
    assert '<root-index trust="untrusted-data">' in prompt
    assert '<numbered-source trust="untrusted-data"' in prompt
    assert "000001 | alpha" in prompt
    assert "000002 | beta" in prompt
    assert "alpha\r" not in prompt
    assert "untrusted data" in captured["instructions"].casefold()
