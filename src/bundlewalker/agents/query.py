from __future__ import annotations

import re
from importlib import resources
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import (
    AgentDependencies,
    frame_untrusted_data,
    metadata_for_agent,
    read_tools,
)
from bundlewalker.domain import (
    MAX_ANSWER_BODY_CHARACTERS,
    MAX_CITATIONS,
    MAX_TITLE_CHARACTERS,
    CitedAnswer,
    OkfDocument,
)
from bundlewalker.errors import AgentRunError, UsageError
from bundlewalker.okf.repository import OkfRepository

type AgentModel = Model | KnownModelName | str

_CITATION_MARKER = re.compile(r"\[(\d+)]")
_MAX_CITATION_NUMBER = MAX_CITATIONS
_MAX_CITATION_DIGITS = len(str(_MAX_CITATION_NUMBER))
_MAX_CITATION_MARKERS = 1_000


def create_query_agent(
    model: AgentModel,
    *,
    refresh: bool = False,
) -> Agent[AgentDependencies, CitedAnswer]:
    """Create the provider-neutral query agent with read-only knowledge tools."""
    instructions = _read_prompt("query.md")
    if refresh:
        instructions += "\n\n" + _read_prompt("query-refresh.md")
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
    return await _run_query_agent(model, dependencies, question, refresh_target=None)


async def run_refresh_query_agent(
    model: AgentModel,
    dependencies: AgentDependencies,
    question: str,
    refresh_target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    """Revise one synthesis using explicit untrusted prior context and fresh citations."""
    return await _run_query_agent(
        model,
        dependencies,
        question,
        refresh_target=refresh_target,
    )


async def _run_query_agent(
    model: AgentModel,
    dependencies: AgentDependencies,
    question: str,
    *,
    refresh_target: OkfDocument | None,
) -> tuple[CitedAnswer, frozenset[str]]:
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
    if refresh_target is not None:
        payload["refresh_target"] = {
            "concept_id": refresh_target.concept_id,
            "metadata": metadata_for_agent(refresh_target.metadata),
            "body": {
                "character_count": len(refresh_target.body),
                "content": refresh_target.body,
            },
        }
    try:
        result = await create_query_agent(model, refresh=refresh_target is not None).run(
            frame_untrusted_data(payload),
            deps=dependencies,
        )
    except Exception:
        pass
    else:
        run_reads = frozenset(dependencies.read_ids).difference(previous_reads)
        if refresh_target is not None:
            _validate_no_refresh_self_citation(result.output, refresh_target.concept_id)
        validate_cited_answer(result.output, dependencies.repository, run_reads)
        return result.output, frozenset(run_reads)
    raise AgentRunError("query agent could not produce an answer") from None


def _read_prompt(name: str) -> str:
    return resources.files("bundlewalker.agents.prompts").joinpath(name).read_text(encoding="utf-8")


def _validate_no_refresh_self_citation(answer: CitedAnswer, concept_id: str) -> None:
    if any(citation.concept_id == concept_id for citation in answer.citations):
        raise AgentRunError(f"refreshed synthesis cannot cite itself: {concept_id}")


def validate_cited_answer(
    answer: CitedAnswer,
    repository: OkfRepository,
    read_ids: frozenset[str],
) -> None:
    """Reject malformed, nonexistent, or unread concept citations."""
    error_message: str | None = None
    try:
        _validate_cited_answer(answer, repository, read_ids)
    except AgentRunError as exc:
        error_message = str(exc)
    except Exception:
        error_message = "query citations could not be checked"
    if error_message is not None:
        raise AgentRunError(error_message) from None


def _validate_cited_answer(
    answer: CitedAnswer,
    repository: OkfRepository,
    read_ids: frozenset[str],
) -> None:
    if len(answer.title) > MAX_TITLE_CHARACTERS or len(answer.body) > MAX_ANSWER_BODY_CHARACTERS:
        raise AgentRunError("query answer exceeds the supported output size")
    if len(answer.citations) > MAX_CITATIONS:
        raise AgentRunError("query answer contains too many structured citations")
    if not answer.title.strip():
        raise AgentRunError("query answer title must not be empty")
    if not answer.body.strip():
        raise AgentRunError("query answer body must not be empty")

    marker_numbers = _bounded_marker_numbers(answer.body)
    if not marker_numbers and not answer.citations:
        raise AgentRunError("query answer must include at least one citation")
    if len(answer.citations) > _MAX_CITATION_NUMBER:
        raise AgentRunError("query answer contains too many structured citations")

    citation_numbers: set[int] = set()
    for citation in answer.citations:
        if citation.start_line is not None or citation.end_line is not None:
            raise AgentRunError("query answer citations cannot include raw line spans")
        if citation.number > _MAX_CITATION_NUMBER:
            raise AgentRunError("query citation number exceeds the supported limit")
        if citation.number in citation_numbers:
            raise AgentRunError("query citation markers do not match structured citations")
        citation_numbers.add(citation.number)
    if marker_numbers != citation_numbers:
        raise AgentRunError("query citation markers do not match structured citations")

    documents = repository.scan()
    for citation in answer.citations:
        if citation.concept_id not in documents:
            raise AgentRunError(f"query citation target does not exist: {citation.concept_id}")
        if citation.concept_id not in read_ids:
            raise AgentRunError(f"query citation target was not read: {citation.concept_id}")


def _bounded_marker_numbers(body: str) -> set[int]:
    marker_numbers: set[int] = set()
    expected_new_number = 1
    marker_count = 0
    for match in _CITATION_MARKER.finditer(body):
        marker_count += 1
        if marker_count > _MAX_CITATION_MARKERS:
            raise AgentRunError("query answer contains too many citation markers")

        digits = match.group(1)
        if len(digits) > _MAX_CITATION_DIGITS:
            raise AgentRunError("query citation number exceeds the supported digit limit")
        number = int(digits)
        if number > _MAX_CITATION_NUMBER:
            raise AgentRunError("query citation number exceeds the supported value limit")
        if number in marker_numbers:
            continue
        if number != expected_new_number:
            raise AgentRunError("query citation numbers must be contiguous starting at 1")
        marker_numbers.add(number)
        expected_new_number += 1
    return marker_numbers
