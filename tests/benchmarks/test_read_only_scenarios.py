# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

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
