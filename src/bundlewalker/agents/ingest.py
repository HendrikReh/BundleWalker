# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from importlib import resources
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import AgentDependencies, frame_untrusted_data, read_tools
from bundlewalker.changes import ChangeValidationContext, validate_change_set
from bundlewalker.domain import ChangeSet
from bundlewalker.errors import AgentRunError, ChangeSetError
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
    prompt = frame_untrusted_data(payload)
    agent = create_ingestion_agent(model)

    @agent.output_validator
    def validate_ingestion_output(  # pyright: ignore[reportUnusedFunction]
        ctx: RunContext[AgentDependencies],
        output: ChangeSet,
    ) -> ChangeSet:
        context = ChangeValidationContext(
            mode="ingest",
            repository=ctx.deps.repository,
            readable_concepts=frozenset(ctx.deps.read_ids),
            source=source,
        )
        try:
            validate_change_set(output, context)
        except ChangeSetError as exc:
            raise ModelRetry(str(exc)) from None
        return output

    try:
        result = await agent.run(prompt, deps=dependencies)
    except Exception:
        pass
    else:
        return result.output, frozenset(dependencies.read_ids)
    raise AgentRunError("ingestion agent could not produce a proposal") from None
