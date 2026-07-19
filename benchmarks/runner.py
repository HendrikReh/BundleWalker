# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.metadata
import itertools
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from benchmarks.contracts import (
    CapacityStop,
    EvidenceRecord,
    SampleObservation,
    ScenarioDisposition,
    ScenarioEvidence,
    ScenarioName,
    WorkspaceProfile,
)
from benchmarks.evidence import collect_environment, summarize_samples, write_evidence
from benchmarks.fixtures import GeneratedFixture, generate_fixture, tree_sha256
from benchmarks.profiles import PROFILES, target_ns
from benchmarks.scenarios import SCENARIOS
from benchmarks.scenarios.mutation import MUTATION_SCENARIOS

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MINIMUM_TIMEOUT_SECONDS = 30
_MAX_OBSERVATION_BYTES = 64 * 1024
_PROFILE_ORDER = tuple(PROFILES)


class BenchmarkRunError(RuntimeError):
    """A correctness, isolation, protocol, or harness failure in a benchmark run."""


class _WorkerTimedOut(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunConfig:
    profiles: tuple[WorkspaceProfile, ...]
    output: Path
    work_root: Path
    run_id: str
    correctness_only: bool

    def __post_init__(self) -> None:
        names = tuple(profile.name for profile in self.profiles)
        if not names:
            raise ValueError("at least one benchmark profile is required")
        if len(names) != len(set(names)):
            raise ValueError("benchmark profiles must be unique")
        if names != tuple(sorted(names, key=_PROFILE_ORDER.index)):
            raise ValueError("benchmark profiles must use catalog order")
        if any(profile != PROFILES[profile.name] for profile in self.profiles):
            raise ValueError("benchmark profiles must match the frozen catalog")
        if self.correctness_only and names != ("smoke",):
            raise ValueError("correctness-only runs require exactly the Smoke profile")
        if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.run_id) is None:
            raise ValueError("run_id is not a safe benchmark identifier")


@dataclass(slots=True)
class _RunWorkspace:
    root: Path
    observations: Path
    initializations: Path
    copies: Path
    counter: itertools.count[int]

    @classmethod
    def create(cls, root: Path) -> _RunWorkspace:
        if root.is_symlink():
            raise BenchmarkRunError("benchmark work root must not be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir() or root.is_symlink():
            raise BenchmarkRunError("benchmark work root must be a directory")
        observations = root / "observations"
        initializations = root / "initializations"
        copies = root / "copies"
        for directory in (observations, initializations, copies):
            directory.mkdir(mode=0o700, exist_ok=False)
        return cls(root, observations, initializations, copies, itertools.count())

    def next_token(self, scenario: ScenarioName, profile: str | None) -> str:
        index = next(self.counter)
        profile_token = "environment" if profile is None else profile
        return f"{index:04d}-{profile_token}-{scenario.value}"


def run_benchmarks(config: RunConfig) -> EvidenceRecord:
    started_at = datetime.now(UTC)
    try:
        _validate_run_paths(config)
        workspace = _RunWorkspace.create(config.work_root)
        fixtures = _generate_fixtures(workspace.root, config.profiles)
        scenarios: list[ScenarioEvidence] = []
        initialization = _measure_scenario(
            workspace=workspace,
            scenario=ScenarioName.INITIALIZE,
            fixture=None,
            correctness_only=config.correctness_only,
        )
        scenarios.append(initialization)

        capacity_stop: CapacityStop | None = None
        for fixture in fixtures:
            for scenario in SCENARIOS:
                try:
                    evidence = _measure_scenario(
                        workspace=workspace,
                        scenario=scenario,
                        fixture=fixture,
                        correctness_only=config.correctness_only,
                    )
                except _WorkerTimedOut:
                    if fixture.profile.name == "large":
                        stopped_profile: Literal["large", "probe"] = "large"
                    elif fixture.profile.name == "probe":
                        stopped_profile = "probe"
                    else:
                        raise BenchmarkRunError(
                            "benchmark worker exceeded a hard deadline"
                        ) from None
                    capacity_stop = CapacityStop(
                        profile=stopped_profile,
                        scenario=scenario,
                        deadline_ns=_deadline_seconds(scenario) * 1_000_000_000,
                    )
                    break
                scenarios.append(evidence)
            if capacity_stop is not None:
                break

        disposition = _overall_disposition(scenarios, capacity_stop)
        git_commit = _git_commit()
        bundlewalker_version = importlib.metadata.version("bundlewalker")
        environment = collect_environment(workspace.root)
        if environment.filesystem_type == "/":
            environment = environment.model_copy(update={"filesystem_type": None})
        completed_at = datetime.now(UTC)
        evidence_record = EvidenceRecord(
            run_id=config.run_id,
            started_at=started_at,
            completed_at=completed_at,
            git_commit=git_commit,
            bundlewalker_version=bundlewalker_version,
            environment=environment,
            profiles=config.profiles,
            fixtures=tuple(fixture.identity() for fixture in fixtures),
            correctness_only=config.correctness_only,
            warmup_count=0 if config.correctness_only else 1,
            read_only_repetitions=1 if config.correctness_only else 7,
            mutation_repetitions=1 if config.correctness_only else 5,
            scenarios=tuple(scenarios),
            capacity_stop=capacity_stop,
            disposition=disposition,
        )
        write_evidence(config.output, evidence_record)
    except _WorkerTimedOut:
        raise BenchmarkRunError("environment benchmark worker exceeded a hard deadline") from None
    except BenchmarkRunError:
        raise
    except Exception as error:
        raise BenchmarkRunError(f"benchmark harness failed: {type(error).__name__}") from error
    return evidence_record


def _validate_run_paths(config: RunConfig) -> None:
    if os.path.lexists(config.output):
        raise BenchmarkRunError("benchmark output already exists")
    if not config.output.parent.is_dir() or config.output.parent.is_symlink():
        raise BenchmarkRunError("benchmark output parent must be an existing directory")
    output = Path(os.path.abspath(config.output))
    work_root = Path(os.path.abspath(config.work_root))
    if output == work_root or output.is_relative_to(work_root):
        raise BenchmarkRunError("benchmark output must be outside the work root")


def _generate_fixtures(
    work_root: Path, profiles: Sequence[WorkspaceProfile]
) -> tuple[GeneratedFixture, ...]:
    fixture_root = work_root / "fixtures"
    fixture_root.mkdir(mode=0o700, exist_ok=False)
    return tuple(generate_fixture(fixture_root / profile.name, profile) for profile in profiles)


def _measure_scenario(
    *,
    workspace: _RunWorkspace,
    scenario: ScenarioName,
    fixture: GeneratedFixture | None,
    correctness_only: bool,
) -> ScenarioEvidence:
    expected_profile = None if fixture is None else fixture.profile.name
    repetitions = 1 if correctness_only else 5 if scenario in MUTATION_SCENARIOS else 7
    all_observations: list[SampleObservation] = []
    if not correctness_only:
        all_observations.append(_run_worker_sample(workspace, scenario=scenario, fixture=fixture))
    measured = tuple(
        _run_worker_sample(workspace, scenario=scenario, fixture=fixture)
        for _sample in range(repetitions)
    )
    all_observations.extend(measured)

    if any(observation.scenario is not scenario for observation in all_observations):
        raise BenchmarkRunError("worker returned an unexpected scenario")
    if any(observation.profile != expected_profile for observation in all_observations):
        raise BenchmarkRunError("worker returned an unexpected profile")
    if len({observation.output_sha256 for observation in all_observations}) != 1:
        raise BenchmarkRunError("worker output digest changed across repetitions")
    try:
        return summarize_samples(
            measured,
            target_ns(scenario),
            correctness_only=correctness_only,
        )
    except ValueError as error:
        raise BenchmarkRunError("worker observations failed summary validation") from error


def _run_worker_sample(
    workspace: _RunWorkspace,
    *,
    scenario: ScenarioName,
    fixture: GeneratedFixture | None,
) -> SampleObservation:
    profile_name = None if fixture is None else fixture.profile.name
    token = workspace.next_token(scenario, profile_name)
    measured_workspace = _sample_workspace(workspace, token, scenario, fixture)
    observation_directory = workspace.observations / token
    observation_directory.mkdir(mode=0o700)
    observation_path = observation_directory / "observation.json"
    command = [
        sys.executable,
        "-m",
        "benchmarks.worker",
        "--scenario",
        scenario.value,
        "--workspace",
        str(measured_workspace),
    ]
    if profile_name is not None:
        command.extend(("--profile", profile_name))
    command.extend(("--output", str(observation_path)))

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=_deadline_seconds(scenario),
            cwd=_PROJECT_ROOT,
            env={},
        )
    except subprocess.TimeoutExpired as error:
        raise _WorkerTimedOut from error
    except OSError as error:
        raise BenchmarkRunError("benchmark worker could not be launched") from error

    if result.returncode != 0:
        raise BenchmarkRunError("benchmark worker reported a bounded failure")
    if result.stdout or result.stderr:
        raise BenchmarkRunError("benchmark worker violated the stdio protocol")
    observation = _load_exclusive_observation(observation_directory, observation_path)
    if (
        fixture is not None
        and scenario not in MUTATION_SCENARIOS
        and tree_sha256(measured_workspace) != fixture.tree_sha256
    ):
        raise BenchmarkRunError("read-only worker changed the generated fixture")
    return observation


def _sample_workspace(
    workspace: _RunWorkspace,
    token: str,
    scenario: ScenarioName,
    fixture: GeneratedFixture | None,
) -> Path:
    if scenario is ScenarioName.INITIALIZE:
        if fixture is not None:
            raise BenchmarkRunError("initialization must be independent of profiles")
        return workspace.initializations / token
    if fixture is None:
        raise BenchmarkRunError("profile scenario requires a generated fixture")
    if scenario not in MUTATION_SCENARIOS:
        return fixture.workspace.root
    destination = workspace.copies / token
    shutil.copytree(fixture.workspace.root, destination, symlinks=False)
    return destination


def _load_exclusive_observation(directory: Path, expected: Path) -> SampleObservation:
    entries = tuple(directory.iterdir())
    complete_entries = tuple(path for path in entries if not path.name.startswith("."))
    if complete_entries != (expected,):
        raise BenchmarkRunError("worker must publish exactly one observation file")
    _validate_atomic_observation_artifacts(entries, expected)
    metadata = expected.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_OBSERVATION_BYTES:
        raise BenchmarkRunError("worker observation must be one bounded regular file")
    try:
        content = expected.read_text(encoding="utf-8")
        return SampleObservation.model_validate_json(content)
    except (OSError, UnicodeError, ValueError) as error:
        raise BenchmarkRunError("worker observation failed strict schema validation") from error


def _validate_atomic_observation_artifacts(entries: Sequence[Path], expected: Path) -> None:
    partials = tuple(
        path
        for path in entries
        if path.name.startswith(f".{expected.name}.") and path.name.endswith(".partial")
    )
    quarantines = tuple(
        path
        for path in entries
        if path.name.startswith(f"..{expected.name}.") and ".partial.cleanup-" in path.name
    )
    if len(entries) != 3 or len(partials) != 1 or len(quarantines) != 1:
        raise BenchmarkRunError("worker left unexpected observation output residue")
    quarantine = quarantines[0]
    if quarantine.is_symlink() or not quarantine.is_dir():
        raise BenchmarkRunError("worker observation quarantine is invalid")
    candidates = tuple(quarantine.iterdir())
    if len(candidates) != 1 or candidates[0].name != "candidate":
        raise BenchmarkRunError("worker observation quarantine contains cleanup residue")
    identities: set[tuple[int, int]] = set()
    for path in (expected, partials[0], candidates[0]):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise BenchmarkRunError("worker observation artifacts must be regular files")
        identities.add((metadata.st_dev, metadata.st_ino))
    if len(identities) != 1:
        raise BenchmarkRunError("worker observation artifacts changed during publication")


def _deadline_seconds(scenario: ScenarioName) -> int:
    target_seconds = target_ns(scenario) // 1_000_000_000
    return max(_MINIMUM_TIMEOUT_SECONDS, 3 * target_seconds)


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            cwd=_PROJECT_ROOT,
            env={},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BenchmarkRunError("Git commit identity could not be resolved") from error
    commit = result.stdout.strip()
    if result.returncode != 0 or result.stderr or _GIT_SHA.fullmatch(commit) is None:
        raise BenchmarkRunError("Git commit identity is not a lowercase SHA-1")
    return commit


def _overall_disposition(
    scenarios: Sequence[ScenarioEvidence], capacity_stop: CapacityStop | None
) -> ScenarioDisposition:
    if capacity_stop is not None:
        return ScenarioDisposition.CAPACITY_EXCEEDED
    if any(item.disposition is ScenarioDisposition.TARGET_MISSED for item in scenarios):
        return ScenarioDisposition.TARGET_MISSED
    return ScenarioDisposition.PASS
