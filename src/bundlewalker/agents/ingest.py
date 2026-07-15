from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import AgentDependencies, read_tools
from bundlewalker.domain import ChangeSet
from bundlewalker.errors import AgentRunError
from bundlewalker.workspace import RawSource

type AgentModel = Model | KnownModelName | str


def create_ingestion_agent(model: AgentModel) -> Agent[AgentDependencies, ChangeSet]:
    """Create the provider-neutral ingestion agent with read-only knowledge tools."""
    instructions = (
        resources.files("bundlewalker.agents.prompts")
        .joinpath("ingest.md")
        .read_text(encoding="utf-8")
    )
    return Agent(
        model,
        deps_type=AgentDependencies,
        output_type=ChangeSet,
        tools=read_tools,
        retries=2,
        instructions=instructions,
    )


async def run_ingestion_agent(
    model: AgentModel,
    dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    """Run one ingestion proposal and return its read-history snapshot."""
    numbered_source = "\n".join(
        f"{number:06d} | {line}" for number, line in enumerate(source.text.splitlines(), start=1)
    )
    payload: dict[str, Any] = {
        "workspace_conventions": {
            "character_count": len(dependencies.conventions),
            "content": dependencies.conventions,
        },
        "root_index": {
            "character_count": len(dependencies.root_index),
            "content": dependencies.root_index,
        },
        "numbered_source": {
            "character_count": len(numbered_source),
            "concept_id": source.concept_id,
            "content": numbered_source,
            "sha256": source.sha256,
        },
    }
    prompt = f"UNTRUSTED_DATA_JSON_V1\n{_escaped_json(payload)}"
    try:
        result = await create_ingestion_agent(model).run(prompt, deps=dependencies)
    except Exception:
        pass
    else:
        return result.output, frozenset(dependencies.read_ids)
    raise AgentRunError("ingestion agent could not produce a proposal") from None


def _escaped_json(value: dict[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return serialized.replace("&", r"\u0026").replace("<", r"\u003c").replace(">", r"\u003e")
