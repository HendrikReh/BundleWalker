from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from bundlewalker.agents.common import (
    AgentDependencies,
    list_concepts,
    read_concept,
    read_tools,
    resolve_model,
    search_concepts,
)
from bundlewalker.domain import OkfDocument, OkfMetadata
from bundlewalker.errors import ConfigurationError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever


def _write_concept(
    root: Path,
    concept_id: str,
    *,
    concept_type: str = "Topic",
    title: str,
    description: str = "A concept used by the agent tools.",
    body: str = "# Notes\n",
) -> None:
    path = root / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"type: {concept_type}\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "tags: [agents, tools]\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )


@pytest.fixture
def dependencies(tmp_path: Path) -> AgentDependencies:
    root = tmp_path / "wiki"
    for index in range(55):
        _write_concept(
            root,
            f"topics/agent-{index:02}",
            title=f"Agent {index:02}",
            body="# Agent\n\nTyped agent tools are bounded.\n",
        )
    _write_concept(
        root,
        "topics/nested/context",
        title="Nested context",
    )
    _write_concept(
        root,
        "entities/large",
        concept_type="Entity",
        title="Large body",
        body="x" * 64_001,
    )
    repository = OkfRepository(root)
    return AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="# Conventions",
        root_index="# Knowledge Index",
    )


def _context(dependencies: AgentDependencies) -> RunContext[AgentDependencies]:
    return RunContext(deps=dependencies, model=TestModel(), usage=RunUsage())


def test_explicit_model_overrides_environment() -> None:
    environment: Mapping[str, str] = {"BUNDLEWALKER_MODEL": "anthropic:environment"}

    assert resolve_model("openai:explicit", environment) == "openai:explicit"


def test_environment_model_is_fallback() -> None:
    assert resolve_model(None, {"BUNDLEWALKER_MODEL": "anthropic:environment"}) == (
        "anthropic:environment"
    )


def test_missing_model_names_both_configuration_methods() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_model(None, {})

    message = str(exc_info.value)
    assert "--model" in message
    assert "BUNDLEWALKER_MODEL" in message


def test_list_concepts_is_bounded_and_includes_child_directories(
    dependencies: AgentDependencies,
) -> None:
    result = list_concepts(_context(dependencies), "topics")

    assert isinstance(result, list)
    assert len(result) == 50
    assert result[0] == {"kind": "directory", "path": "topics/nested"}
    assert result[1]["kind"] == "concept"
    json.dumps(result)


def test_list_concepts_rejects_path_traversal(
    dependencies: AgentDependencies,
) -> None:
    result = list_concepts(_context(dependencies), "../raw")

    assert isinstance(result, dict)
    assert "error" in result
    assert "unsafe" in result["error"]


def test_search_concepts_caps_requested_limit_at_ten(
    dependencies: AgentDependencies,
) -> None:
    result = search_concepts(_context(dependencies), "agent", limit=100)

    assert isinstance(result, list)
    assert len(result) == 10
    assert all(item["kind"] == "concept" for item in result)
    json.dumps(result)


def test_search_concepts_filters_by_type(
    dependencies: AgentDependencies,
) -> None:
    result = search_concepts(
        _context(dependencies),
        "large body",
        type="Entity",
        limit=10,
    )

    assert isinstance(result, list)
    assert [item["concept_id"] for item in result] == ["entities/large"]


def test_read_concept_caps_body_and_records_successful_read(
    dependencies: AgentDependencies,
) -> None:
    result = read_concept(_context(dependencies), "entities/large")

    assert "error" not in result
    assert result["concept_id"] == "entities/large"
    assert len(result["body"]) == 64_000
    assert result["truncated"] is True
    assert "path" not in result
    assert dependencies.read_ids == {"entities/large"}
    json.dumps(result)


def test_read_concept_returns_safe_error_without_recording_missing_id(
    dependencies: AgentDependencies,
) -> None:
    result = read_concept(_context(dependencies), "topics/missing")

    assert result == {"error": "concept not found: topics/missing"}
    assert dependencies.read_ids == set()


def test_read_concept_rejects_traversal_without_recording_it(
    dependencies: AgentDependencies,
) -> None:
    result = read_concept(_context(dependencies), "../raw/secret")

    assert "error" in result
    assert "unsafe" in result["error"]
    assert dependencies.read_ids == set()


def test_read_concept_converts_nested_binary_metadata_to_url_safe_base64(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "binary.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "type: Topic\n"
        "title: Binary metadata\n"
        "description: Exercises permissive OKF extensions.\n"
        "extension:\n"
        "  payloads:\n"
        "    - !!binary /w==\n"
        "  mapping:\n"
        "    ? !!binary /w==\n"
        "    : binary-key\n"
        "---\n"
        "# Binary metadata\n",
        encoding="utf-8",
    )
    repository = OkfRepository(root)
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="# Conventions",
        root_index="# Knowledge Index",
    )

    result = read_concept(_context(dependencies), "topics/binary")

    assert "error" not in result
    assert result["metadata"]["extension"] == {
        "payloads": ["_w=="],
        "mapping": {"_w==": "binary-key"},
    }
    json.dumps(result, allow_nan=False)
    assert dependencies.read_ids == {"topics/binary"}


def test_read_concept_converts_nested_non_finite_floats_to_stable_strings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "non-finite.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "type: Topic\n"
        "title: Non-finite metadata\n"
        "description: Exercises permissive numeric extensions.\n"
        "extension:\n"
        "  values: [.nan, .inf, -.inf]\n"
        "---\n"
        "# Non-finite metadata\n",
        encoding="utf-8",
    )
    repository = OkfRepository(root)
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="# Conventions",
        root_index="# Knowledge Index",
    )

    result = read_concept(_context(dependencies), "topics/non-finite")

    assert "error" not in result
    assert result["metadata"]["extension"] == {"values": ["NaN", "Infinity", "-Infinity"]}
    json.dumps(result, allow_nan=False)
    assert dependencies.read_ids == {"topics/non-finite"}


def test_read_concept_sorts_nested_sets_by_canonical_json_across_hash_seeds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "set.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "type: Topic\n"
        "title: Set metadata\n"
        "description: Exercises permissive unordered extensions.\n"
        "extension:\n"
        "  labels: !!set {zeta: null, alpha: null, middle: null}\n"
        "---\n"
        "# Set metadata\n",
        encoding="utf-8",
    )
    script = """
import json
import sys
from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from bundlewalker.agents.common import AgentDependencies, read_concept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever

repository = OkfRepository(Path(sys.argv[1]))
dependencies = AgentDependencies(repository, LexicalRetriever(repository), "", "")
context = RunContext(deps=dependencies, model=TestModel(), usage=RunUsage())
result = read_concept(context, "topics/set")
print(json.dumps(result["metadata"]["extension"]["labels"]))
"""

    results: list[list[str]] = []
    for seed in ("1", "2", "3", "4", "5"):
        completed = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        results.append(cast(list[str], json.loads(completed.stdout)))

    assert results == [["alpha", "middle", "zeta"]] * 5


def test_read_concept_serialization_failure_is_safe_and_not_recorded() -> None:
    document = OkfDocument(
        concept_id="topics/unserializable",
        path=Path("topics/unserializable.md"),
        metadata=OkfMetadata.model_validate({"type": "Topic", "extension": object()}),
        body="# Unserializable\n",
        digest="a" * 64,
    )

    class StaticRepository(OkfRepository):
        def get(self, concept_id: str) -> OkfDocument:
            assert concept_id == document.concept_id
            return document

    repository = StaticRepository(Path("wiki"))
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions="# Conventions",
        root_index="# Knowledge Index",
    )

    result = read_concept(_context(dependencies), document.concept_id)

    assert result == {"error": "concept could not be serialized: topics/unserializable"}
    json.dumps(result, allow_nan=False)
    assert dependencies.read_ids == set()


def test_read_tools_register_exactly_the_three_read_only_functions() -> None:
    names = {tool.__name__ for tool in read_tools}

    assert names == {"list_concepts", "search_concepts", "read_concept"}
    assert all(
        forbidden not in name for forbidden in ("write", "delete", "rename") for name in names
    )
