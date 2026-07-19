# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
from typing import NoReturn

import pytest

import benchmarks.scenarios.read_only as read_only
from benchmarks.contracts import ScenarioName
from benchmarks.fixtures import generate_fixture, tree_sha256
from benchmarks.profiles import PROFILES
from benchmarks.scenarios.read_only import run_initialization, run_read_only


@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioName.STATUS,
        ScenarioName.LIST_CONCEPTS,
        ScenarioName.READ_CONCEPT,
        ScenarioName.SEARCH_PRESENT,
        ScenarioName.SEARCH_ABSENT,
        ScenarioName.LINT,
    ],
)
def test_read_only_scenarios_are_correct_and_do_not_mutate(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / scenario.value, PROFILES["smoke"])
    before = fixture.tree_sha256
    observation = run_read_only(scenario, fixture)

    assert observation.scenario is scenario
    assert observation.profile == "smoke"
    assert observation.duration_ns >= 0
    assert len(observation.output_sha256) == 64
    assert tree_sha256(fixture.workspace.root) == before


def test_initialization_measures_a_new_standard_workspace(tmp_path: Path) -> None:
    observation = run_initialization(tmp_path / "new-workspace")
    assert observation.scenario is ScenarioName.INITIALIZE
    assert observation.profile is None
    assert observation.checkpoint_bytes["initialized_workspace"] > 0


@pytest.mark.parametrize("destination_kind", ["directory", "file"])
def test_initialization_rejects_existing_destination_before_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    destination_kind: str,
) -> None:
    destination = tmp_path / "existing"
    if destination_kind == "directory":
        destination.mkdir()
    else:
        destination.write_text("keep", encoding="ascii")

    calls: list[str] = []

    class RecordingClock:
        @staticmethod
        def perf_counter_ns() -> int:
            calls.append("timer")
            return 0

    def unexpected_initialization(_destination: Path) -> NoReturn:
        calls.append("initialize")
        raise AssertionError("initialize_workspace must not be called")

    monkeypatch.setattr(read_only, "time", RecordingClock)
    monkeypatch.setattr(read_only, "initialize_workspace", unexpected_initialization)

    with pytest.raises(ValueError, match="must not exist"):
        run_initialization(destination)

    assert calls == []
    if destination_kind == "directory":
        assert list(destination.iterdir()) == []
    else:
        assert destination.read_text(encoding="ascii") == "keep"
