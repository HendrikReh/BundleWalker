# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel

from benchmarks.contracts import SampleObservation, ScenarioName
from benchmarks.fixtures import GeneratedFixture
from benchmarks.scenarios import ScenarioCallable
from bundlewalker.application.contracts import (
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    LintResult,
    WorkspaceStatus,
)
from bundlewalker.application.facade import WorkspaceApplication
from bundlewalker.okf.lint import lint_bundle
from bundlewalker.workspace import WorkspaceConfig, discover_workspace, initialize_workspace


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _output_sha256(value: object) -> str:
    canonical = json.dumps(
        _jsonable(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _measure(
    fixture: GeneratedFixture,
    scenario: ScenarioName,
    operation: Callable[[], object],
) -> SampleObservation:
    started = time.perf_counter_ns()
    result = operation()
    duration = time.perf_counter_ns() - started
    _assert_correct(fixture, scenario, result)
    return SampleObservation(
        scenario=scenario,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=_output_sha256(result),
    )


def _assert_correct(fixture: GeneratedFixture, scenario: ScenarioName, result: object) -> None:
    if scenario is ScenarioName.STATUS:
        assert isinstance(result, WorkspaceStatus)
        assert sum(result.concept_counts.values()) == fixture.profile.document_count
        assert result.pending_review is None
        return
    if scenario is ScenarioName.LIST_CONCEPTS:
        assert isinstance(result, ConceptPage)
        expected = tuple(sorted(fixture.concept_ids)[:100])
        assert tuple(item.concept_id for item in result.items) == expected
        return
    if scenario is ScenarioName.READ_CONCEPT:
        assert isinstance(result, ConceptContent)
        assert result.concept_id == fixture.read_concept_id
        assert fixture.present_query in result.markdown
        return
    if scenario is ScenarioName.SEARCH_PRESENT:
        assert isinstance(result, ConceptSearchResult)
        assert result.items
        assert result.items[0].concept_id == fixture.read_concept_id
        return
    if scenario is ScenarioName.SEARCH_ABSENT:
        assert isinstance(result, ConceptSearchResult)
        assert result.items == ()
        return
    if scenario is ScenarioName.LINT:
        assert isinstance(result, LintResult)
        assert result.findings == ()
        assert result.deterministic_has_errors is False
        return
    raise ValueError(f"unsupported read-only scenario: {scenario.value}")


def _run_status(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(fixture, ScenarioName.STATUS, lambda: asyncio.run(application.status()))


def _run_list_concepts(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(
        fixture,
        ScenarioName.LIST_CONCEPTS,
        lambda: asyncio.run(application.list_concepts(limit=100)),
    )


def _run_read_concept(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(
        fixture,
        ScenarioName.READ_CONCEPT,
        lambda: asyncio.run(application.read_concept(fixture.read_concept_id)),
    )


def _run_search_present(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(
        fixture,
        ScenarioName.SEARCH_PRESENT,
        lambda: asyncio.run(application.search_concepts(fixture.present_query)),
    )


def _run_search_absent(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(
        fixture,
        ScenarioName.SEARCH_ABSENT,
        lambda: asyncio.run(application.search_concepts(fixture.absent_query)),
    )


def _run_lint(fixture: GeneratedFixture) -> SampleObservation:
    application = WorkspaceApplication(fixture.workspace)
    return _measure(
        fixture,
        ScenarioName.LINT,
        lambda: asyncio.run(application.lint(semantic=False, explicit_model=None)),
    )


READ_ONLY_SCENARIOS: Mapping[ScenarioName, ScenarioCallable] = MappingProxyType(
    {
        ScenarioName.STATUS: _run_status,
        ScenarioName.LIST_CONCEPTS: _run_list_concepts,
        ScenarioName.READ_CONCEPT: _run_read_concept,
        ScenarioName.SEARCH_PRESENT: _run_search_present,
        ScenarioName.SEARCH_ABSENT: _run_search_absent,
        ScenarioName.LINT: _run_lint,
    }
)


def run_read_only(scenario: ScenarioName, fixture: GeneratedFixture) -> SampleObservation:
    return READ_ONLY_SCENARIOS[scenario](fixture)


def run_initialization(destination: Path) -> SampleObservation:
    started = time.perf_counter_ns()
    workspace = initialize_workspace(destination)
    duration = time.perf_counter_ns() - started

    discovered = discover_workspace(destination)
    assert discovered == workspace
    assert workspace.config == WorkspaceConfig()
    assert lint_bundle(workspace.wiki_dir, workspace.root) == []
    initialized_bytes = _tree_size(workspace.root)
    assert initialized_bytes > 0
    validated: dict[str, object] = {
        "config": {
            "conventions_file": workspace.config.conventions_file,
            "max_source_characters": workspace.config.max_source_characters,
            "raw_dir": workspace.config.raw_dir,
            "version": workspace.config.version,
            "wiki_dir": workspace.config.wiki_dir,
        },
        "deterministic_findings": (),
    }
    return SampleObservation(
        scenario=ScenarioName.INITIALIZE,
        profile=None,
        duration_ns=duration,
        output_sha256=_output_sha256(validated),
        checkpoint_bytes={"initialized_workspace": initialized_bytes},
    )


def _tree_size(root: Path) -> int:
    return sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )
