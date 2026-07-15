from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal, TypedDict

from pydantic_ai import RunContext

from bundlewalker.errors import ConfigurationError, OkfError, UsageError
from bundlewalker.okf.repository import ConceptSummary, OkfRepository
from bundlewalker.retrieval import LexicalRetriever

_MODEL_ENVIRONMENT_VARIABLE = "BUNDLEWALKER_MODEL"
_MAX_LIST_ENTRIES = 50
_MAX_SEARCH_RESULTS = 10
_MAX_BODY_CHARACTERS = 64_000


class DirectoryEntry(TypedDict):
    kind: Literal["directory"]
    path: str


class ConceptEntry(TypedDict):
    kind: Literal["concept"]
    concept_id: str
    type: str
    title: str | None
    description: str | None
    tags: list[str]


class ToolError(TypedDict):
    error: str


class ReadResult(TypedDict):
    concept_id: str
    metadata: dict[str, Any]
    body: str
    links: list[str]
    digest: str
    truncated: bool


type ListResult = list[DirectoryEntry | ConceptEntry] | ToolError
type SearchResult = list[ConceptEntry] | ToolError
type ConceptReadResult = ReadResult | ToolError


@dataclass(slots=True)
class AgentDependencies:
    repository: OkfRepository
    retriever: LexicalRetriever
    conventions: str
    root_index: str
    read_ids: set[str] = field(default_factory=set[str])


def resolve_model(explicit_model: str | None, environment: Mapping[str, str]) -> str:
    """Resolve an agent model without reading or mutating process environment state."""
    if explicit_model is not None and (model := explicit_model.strip()):
        return model
    if model := environment.get(_MODEL_ENVIRONMENT_VARIABLE, "").strip():
        return model
    raise ConfigurationError(
        "an agent model is required; pass --model MODEL or set BUNDLEWALKER_MODEL"
    )


def list_concepts(
    ctx: RunContext[AgentDependencies],
    path: str = "",
) -> ListResult:
    """List at most 50 immediate wiki entries below a safe relative directory.

    Args:
        ctx: The current agent run context.
        path: A wiki-relative directory without an absolute path or ``..`` traversal.
    """
    try:
        concepts = ctx.deps.repository.list(path)
        directories = _child_directories(ctx.deps.repository, path)
    except OkfError as exc:
        return _tool_error(exc)

    entries: list[DirectoryEntry | ConceptEntry] = [
        DirectoryEntry(kind="directory", path=directory) for directory in directories
    ]
    entries.extend(_summary_entry(summary) for summary in concepts)
    return entries[:_MAX_LIST_ENTRIES]


def search_concepts(
    ctx: RunContext[AgentDependencies],
    query: str,
    type: str | None = None,
    limit: int = _MAX_SEARCH_RESULTS,
) -> SearchResult:
    """Search wiki metadata and return at most ten ranked concept summaries.

    Args:
        ctx: The current agent run context.
        query: Text to match against concept metadata and bodies.
        type: An optional exact OKF concept type filter.
        limit: Requested result count; values above ten are capped at ten.
    """
    if limit < 1:
        return ToolError(error="search limit must be at least 1")
    bounded_limit = min(limit, _MAX_SEARCH_RESULTS)
    try:
        summaries = ctx.deps.retriever.search(query, type, bounded_limit)
    except (OkfError, UsageError) as exc:
        return _tool_error(exc)
    return [_summary_entry(summary) for summary in summaries]


def read_concept(
    ctx: RunContext[AgentDependencies],
    concept_id: str,
) -> ConceptReadResult:
    """Read one safe wiki concept, capped at 64,000 body characters.

    Args:
        ctx: The current agent run context.
        concept_id: A wiki-relative concept ID without ``.md``, absolute paths, or traversal.
    """
    try:
        document = ctx.deps.repository.get(concept_id)
    except OkfError as exc:
        return _tool_error(exc)

    body = document.body[:_MAX_BODY_CHARACTERS]
    ctx.deps.read_ids.add(document.concept_id)
    return ReadResult(
        concept_id=document.concept_id,
        metadata=document.metadata.model_dump(mode="json"),
        body=body,
        links=list(document.links),
        digest=document.digest,
        truncated=len(document.body) > len(body),
    )


read_tools = (list_concepts, search_concepts, read_concept)


def _summary_entry(summary: ConceptSummary) -> ConceptEntry:
    return ConceptEntry(
        kind="concept",
        concept_id=summary.concept_id,
        type=summary.type,
        title=summary.title,
        description=summary.description,
        tags=list(summary.tags),
    )


def _child_directories(repository: OkfRepository, directory: str) -> list[str]:
    parent = PurePosixPath("." if directory in {"", "."} else directory)
    children: set[str] = set()
    for document in repository.scan().values():
        document_parent = PurePosixPath(document.concept_id).parent
        try:
            relative_parent = document_parent.relative_to(parent)
        except ValueError:
            continue
        if relative_parent.parts:
            children.add((parent / relative_parent.parts[0]).as_posix())
    return sorted(children)


def _tool_error(exc: OkfError | UsageError) -> ToolError:
    return ToolError(error=str(exc))
