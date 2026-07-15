from __future__ import annotations

import re
from importlib import resources
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import AgentDependencies, frame_untrusted_data, read_tools
from bundlewalker.domain import CitedAnswer
from bundlewalker.errors import AgentRunError, OkfError, UsageError
from bundlewalker.okf.repository import OkfRepository

type AgentModel = Model | KnownModelName | str

_CITATION_MARKER = re.compile(r"\[(\d+)]")


def create_query_agent(model: AgentModel) -> Agent[AgentDependencies, CitedAnswer]:
    """Create the provider-neutral query agent with read-only knowledge tools."""
    instructions = (
        resources.files("bundlewalker.agents.prompts")
        .joinpath("query.md")
        .read_text(encoding="utf-8")
    )
    return Agent(
        model,
        deps_type=AgentDependencies,
        output_type=CitedAnswer,
        tools=read_tools,
        retries=2,
        instructions=instructions,
    )


async def run_query_agent(
    model: AgentModel,
    dependencies: AgentDependencies,
    question: str,
) -> tuple[CitedAnswer, frozenset[str]]:
    """Answer one question and verify citations against this run's read ledger."""
    if not question.strip():
        raise UsageError("question must not be empty")

    previous_reads = frozenset(dependencies.read_ids)
    payload: dict[str, Any] = {
        "workspace_conventions": {
            "character_count": len(dependencies.conventions),
            "content": dependencies.conventions,
        },
        "root_index": {
            "character_count": len(dependencies.root_index),
            "content": dependencies.root_index,
        },
        "question": {
            "character_count": len(question),
            "content": question,
        },
    }
    try:
        result = await create_query_agent(model).run(
            frame_untrusted_data(payload),
            deps=dependencies,
        )
    except Exception:
        pass
    else:
        run_reads = frozenset(dependencies.read_ids).difference(previous_reads)
        validate_cited_answer(result.output, dependencies.repository, run_reads)
        return result.output, frozenset(run_reads)
    raise AgentRunError("query agent could not produce an answer") from None


def validate_cited_answer(
    answer: CitedAnswer,
    repository: OkfRepository,
    read_ids: frozenset[str],
) -> None:
    """Reject malformed, nonexistent, or unread concept citations."""
    if not answer.title.strip():
        raise AgentRunError("query answer title must not be empty")
    if not answer.body.strip():
        raise AgentRunError("query answer body must not be empty")

    markers = [int(value) for value in _CITATION_MARKER.findall(answer.body)]
    marker_order = list(dict.fromkeys(markers))
    citation_numbers = [citation.number for citation in answer.citations]
    all_numbers = sorted(set(markers) | set(citation_numbers))
    expected = list(range(1, max(all_numbers) + 1)) if all_numbers else []
    if not all_numbers:
        raise AgentRunError("query answer must include at least one citation")
    if all_numbers != expected or marker_order != expected:
        raise AgentRunError("query citation numbers must be contiguous starting at 1")
    if set(markers) != set(citation_numbers) or len(citation_numbers) != len(set(citation_numbers)):
        raise AgentRunError("query citation markers do not match structured citations")

    try:
        documents = repository.scan()
    except OkfError:
        raise AgentRunError("query citations could not be checked") from None
    for citation in answer.citations:
        if citation.concept_id not in documents:
            raise AgentRunError(f"query citation target does not exist: {citation.concept_id}")
        if citation.concept_id not in read_ids:
            raise AgentRunError(f"query citation target was not read: {citation.concept_id}")
