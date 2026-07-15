from __future__ import annotations

from importlib import resources

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
    prompt = (
        '<workspace-conventions trust="untrusted-data">\n'
        f"{dependencies.conventions}\n"
        "</workspace-conventions>\n\n"
        '<root-index trust="untrusted-data">\n'
        f"{dependencies.root_index}\n"
        "</root-index>\n\n"
        f'<numbered-source trust="untrusted-data" '
        f'source-id="{source.concept_id}" sha256="{source.sha256}">\n'
        f"{numbered_source}\n"
        "</numbered-source>"
    )
    try:
        result = await create_ingestion_agent(model).run(prompt, deps=dependencies)
    except Exception as exc:
        raise AgentRunError("ingestion agent could not produce a proposal") from exc
    return result.output, frozenset(dependencies.read_ids)
