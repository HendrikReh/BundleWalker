# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import importlib.metadata
import itertools
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
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
from benchmarks.fixtures import GeneratedFixture, generate_fixture
from benchmarks.profiles import PROFILES, target_ns
from benchmarks.scenarios import SCENARIOS
from benchmarks.scenarios.mutation import MUTATION_SCENARIOS

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MINIMUM_TIMEOUT_SECONDS = 30
_MAX_OBSERVATION_BYTES = 64 * 1024
_MAX_WORKER_OUTPUT_BYTES = 16 * 1024
_PROCESS_WAIT_SECONDS = 2
_CAPTURE_POLL_SECONDS = 0.05
_PROFILE_ORDER = tuple(PROFILES)


class BenchmarkRunError(RuntimeError):
    """A correctness, isolation, protocol, or harness failure in a benchmark run."""


class _WorkerTimedOut(Exception):
    pass


class _WorkerOutputExceeded(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _WorkerResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    kind: Literal["directory", "file"]
    mode: int
    size: int
    mtime_ns: int
    user_id: int
    group_id: int
    link_count: int
    content_sha256: str | None
    xattrs: tuple[tuple[str, str], ...]


type _TreeSnapshot = dict[str, _TreeEntry]


@dataclass(frozen=True, slots=True)
class _TreeLimits:
    max_entries: int
    max_total_declared_bytes: int
    max_file_bytes: int


type _TreeMetadata = tuple[Literal["directory", "file"], int, int, int, int, int, int]
type _TreeChildren = dict[str, tuple[str, ...]]


@dataclass(slots=True)
class AnchoredPublication:
    descriptor: int
    identity: tuple[int, int]
    leaf: str

    @classmethod
    def open(cls, output: Path) -> AnchoredPublication:
        if os.name != "posix":
            raise OSError("descriptor-anchored publication is unavailable")
        if output.name in {"", ".", ".."}:
            raise OSError("invalid publication leaf")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(output.parent, flags)
        try:
            state = os.fstat(descriptor)
            if not stat.S_ISDIR(state.st_mode):
                raise OSError("publication parent is not a directory")
            return cls(descriptor, (state.st_dev, state.st_ino), output.name)
        except BaseException:
            os.close(descriptor)
            raise

    def publish(self, writer: Callable[[Path], None]) -> None:
        self._validate_identity()
        self._publish_from_directory(writer)
        self._validate_identity()
        os.fsync(self.descriptor)
        self._validate_identity()

    def close(self) -> None:
        descriptor = self.descriptor
        self.descriptor = -1
        if descriptor >= 0:
            os.close(descriptor)

    def _publish_from_directory(self, writer: Callable[[Path], None]) -> None:
        previous = os.open(".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fchdir(self.descriptor)
            writer(Path(self.leaf))
        finally:
            os.fchdir(previous)
            os.close(previous)

    def _validate_identity(self) -> None:
        state = os.fstat(self.descriptor)
        if not stat.S_ISDIR(state.st_mode) or (state.st_dev, state.st_ino) != self.identity:
            raise OSError("publication parent identity changed")


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
    fixture_snapshots: dict[str, _TreeSnapshot]

    @classmethod
    def create(cls, root: Path) -> _RunWorkspace:
        root = _create_unaliased_directory_path(root)
        observations = root / "observations"
        initializations = root / "initializations"
        copies = root / "copies"
        for directory in (observations, initializations, copies):
            directory.mkdir(mode=0o700, exist_ok=False)
        return cls(root, observations, initializations, copies, itertools.count(), {})

    def next_token(self, scenario: ScenarioName, profile: str | None) -> str:
        index = next(self.counter)
        profile_token = "environment" if profile is None else profile
        return f"{index:04d}-{profile_token}-{scenario.value}"


def run_benchmarks(config: RunConfig) -> EvidenceRecord:
    started_at = datetime.now(UTC)
    publication: AnchoredPublication | None = None
    try:
        _validate_run_paths(config)
        publication = AnchoredPublication.open(config.output)
        workspace = _RunWorkspace.create(config.work_root)
        fixtures = _generate_fixtures(workspace.root, config.profiles)
        workspace.fixture_snapshots.update(
            (
                fixture.profile.name,
                _snapshot_tree(fixture.workspace.root, limits=_fixture_tree_limits(fixture)),
            )
            for fixture in fixtures
        )
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
        publication.publish(lambda output: write_evidence(output, evidence_record))
    except _WorkerTimedOut:
        raise BenchmarkRunError("environment benchmark worker exceeded a hard deadline") from None
    except BenchmarkRunError:
        raise
    except Exception as error:
        raise BenchmarkRunError(f"benchmark harness failed: {type(error).__name__}") from error
    finally:
        if publication is not None:
            publication.close()
    return evidence_record


def _validate_run_paths(config: RunConfig) -> None:
    if os.path.lexists(config.output):
        raise BenchmarkRunError("benchmark output already exists")
    output_parent = _require_unaliased_directory(config.output.parent)
    output = output_parent / config.output.name
    work_root = _resolve_intended_directory(config.work_root)
    _reject_bundlewalker_workspace_path(output)
    _reject_bundlewalker_workspace_path(work_root)
    if output == work_root or output.is_relative_to(work_root) or work_root.is_relative_to(output):
        raise BenchmarkRunError("benchmark output must be outside the work root")


def _reject_bundlewalker_workspace_path(candidate: Path) -> None:
    for ancestor in (candidate, *candidate.parents):
        marker = ancestor / "bundlewalker.toml"
        try:
            marker_state = marker.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise BenchmarkRunError("benchmark workspace marker could not be validated") from error
        if stat.S_ISREG(marker_state.st_mode):
            raise BenchmarkRunError("benchmark paths must be outside BundleWalker workspaces")


def _require_unaliased_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    if path.is_symlink() or not path.is_dir():
        raise BenchmarkRunError("benchmark path must be an existing non-symlink directory")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BenchmarkRunError("benchmark path could not be resolved") from error
    if resolved != absolute:
        raise BenchmarkRunError("benchmark path must not cross a symlink boundary")
    return resolved


def _resolve_intended_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    cursor = absolute
    missing_names: list[str] = []
    while not os.path.lexists(cursor):
        if cursor == cursor.parent:
            raise BenchmarkRunError("benchmark path has no existing directory ancestor")
        missing_names.append(cursor.name)
        cursor = cursor.parent
    resolved = _require_unaliased_directory(cursor)
    for name in reversed(missing_names):
        resolved /= name
    return resolved


def _create_unaliased_directory_path(path: Path) -> Path:
    intended = _resolve_intended_directory(path)
    if os.path.lexists(intended):
        return _require_unaliased_directory(intended)
    cursor = intended
    missing: list[Path] = []
    while not os.path.lexists(cursor):
        missing.append(cursor)
        cursor = cursor.parent
    _require_unaliased_directory(cursor)
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError as error:
            raise BenchmarkRunError("benchmark work path changed during creation") from error
        _require_unaliased_directory(directory)
    return _require_unaliased_directory(intended)


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
    expected_snapshot: _TreeSnapshot | None = None
    if fixture is not None:
        expected_snapshot = workspace.fixture_snapshots[fixture.profile.name]
        if (
            _snapshot_tree(
                fixture.workspace.root,
                limits=_limits_for_snapshot(expected_snapshot),
                expected=expected_snapshot,
            )
            != expected_snapshot
        ):
            raise BenchmarkRunError("generated fixture topology changed before worker launch")
    measured_workspace = _sample_workspace(workspace, token, scenario, fixture)
    if (
        fixture is not None
        and scenario in MUTATION_SCENARIOS
        and _snapshot_tree(
            measured_workspace,
            limits=_limits_for_snapshot(expected_snapshot),
            expected=expected_snapshot,
        )
        != expected_snapshot
    ):
        raise BenchmarkRunError("mutation fixture copy topology changed before worker launch")
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

    result = _run_bounded_worker(
        command,
        timeout_seconds=_deadline_seconds(scenario),
        observation_directory=observation_directory,
        observation_path=observation_path,
        measured_workspace=measured_workspace,
        expected_workspace=(
            expected_snapshot
            if fixture is not None and scenario not in MUTATION_SCENARIOS
            else None
        ),
        workspace_limits=(
            _initialization_tree_limits()
            if fixture is None
            else _mutation_tree_limits(fixture)
            if scenario in MUTATION_SCENARIOS
            else _limits_for_snapshot(expected_snapshot)
        ),
    )

    if result.returncode != 0:
        raise BenchmarkRunError("benchmark worker reported a bounded failure")
    if result.stdout or result.stderr:
        raise BenchmarkRunError("benchmark worker violated the stdio protocol")
    observation = _load_exclusive_observation(observation_directory, observation_path)
    if (
        fixture is not None
        and scenario not in MUTATION_SCENARIOS
        and _snapshot_tree(
            measured_workspace,
            limits=_limits_for_snapshot(expected_snapshot),
            expected=expected_snapshot,
        )
        != expected_snapshot
    ):
        raise BenchmarkRunError("read-only worker changed the full filesystem topology")
    return observation


def _run_bounded_worker(
    command: list[str],
    *,
    timeout_seconds: int,
    observation_directory: Path,
    observation_path: Path,
    measured_workspace: Path,
    expected_workspace: _TreeSnapshot | None,
    workspace_limits: _TreeLimits,
) -> _WorkerResult:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=_PROJECT_ROOT,
            env={},
            shell=False,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        raise BenchmarkRunError("benchmark worker could not be launched") from error

    try:
        try:
            stdout, stderr = _capture_worker_output(process, timeout_seconds)
        except _WorkerOutputExceeded as error:
            if not _terminate_worker_tree(process):
                raise BenchmarkRunError("benchmark worker output cleanup did not finish") from error
            _validate_failed_worker_residue(
                observation_directory,
                observation_path,
                measured_workspace,
                expected_workspace,
                workspace_limits,
            )
            raise BenchmarkRunError("benchmark worker exceeded the bounded stdio limit") from error
        except _WorkerTimedOut:
            if not _terminate_worker_tree(process):
                raise BenchmarkRunError(
                    "timed-out benchmark worker tree did not terminate"
                ) from None
            _validate_failed_worker_residue(
                observation_directory,
                observation_path,
                measured_workspace,
                expected_workspace,
                workspace_limits,
            )
            raise

        if _worker_tree_exists(process):
            if not _terminate_worker_tree(process):
                raise BenchmarkRunError("benchmark worker descendant tree did not terminate")
            _validate_failed_worker_residue(
                observation_directory,
                observation_path,
                measured_workspace,
                expected_workspace,
                workspace_limits,
            )
            raise BenchmarkRunError("benchmark worker left a descendant process")
        return _WorkerResult(process.returncode, stdout, stderr)
    except BaseException:
        if _worker_tree_exists(process):
            _terminate_worker_tree(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _capture_worker_output(
    process: subprocess.Popen[bytes], timeout_seconds: int
) -> tuple[bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        raise BenchmarkRunError("benchmark worker pipes were not created")
    selector = selectors.DefaultSelector()
    streams = {
        process.stdout.fileno(): bytearray(),
        process.stderr.fileno(): bytearray(),
    }
    selector.register(process.stdout, selectors.EVENT_READ)
    selector.register(process.stderr, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    try:
        while process.poll() is None or selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _WorkerTimedOut
            if not selector.get_map():
                time.sleep(min(_CAPTURE_POLL_SECONDS, remaining))
                continue
            for key, _events in selector.select(min(_CAPTURE_POLL_SECONDS, remaining)):
                captured = streams[key.fd]
                chunk = os.read(key.fd, min(4096, _MAX_WORKER_OUTPUT_BYTES + 1 - len(captured)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                captured.extend(chunk)
                if len(captured) > _MAX_WORKER_OUTPUT_BYTES:
                    raise _WorkerOutputExceeded
        if process.returncode is None:
            raise BenchmarkRunError("benchmark worker did not publish an exit status")
        return bytes(streams[process.stdout.fileno()]), bytes(streams[process.stderr.fileno()])
    finally:
        selector.close()


def _terminate_worker_tree(process: subprocess.Popen[bytes]) -> bool:
    _signal_worker_tree(process, signal.SIGTERM)
    if _wait_for_worker_tree_exit(process, _PROCESS_WAIT_SECONDS):
        return True
    _signal_worker_tree(process, signal.SIGKILL)
    return _wait_for_worker_tree_exit(process, _PROCESS_WAIT_SECONDS)


def _signal_worker_tree(process: subprocess.Popen[bytes], requested_signal: signal.Signals) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, requested_signal)
        elif requested_signal is signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        return
    except PermissionError:
        # Darwin may deny a group signal when any group member is unsignalable.
        # The bounded liveness wait determines whether cleanup actually finished.
        return


def _wait_for_worker_tree_exit(process: subprocess.Popen[bytes], timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        process.poll()
        if not _worker_tree_exists(process):
            return True
        time.sleep(_CAPTURE_POLL_SECONDS)
    process.poll()
    return not _worker_tree_exists(process)


def _worker_tree_exists(process: subprocess.Popen[bytes]) -> bool:
    if os.name != "posix":
        return process.poll() is None
    return _worker_group_exists(process.pid)


def _worker_group_exists(process_id: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # A denied group probe cannot prove that the worker tree is gone.
        return True
    return True


def _validate_failed_worker_residue(
    observation_directory: Path,
    observation_path: Path,
    measured_workspace: Path,
    expected_workspace: _TreeSnapshot | None,
    workspace_limits: _TreeLimits,
) -> None:
    _snapshot_tree(
        observation_directory,
        limits=_TreeLimits(
            max_entries=8,
            max_total_declared_bytes=4 * _MAX_OBSERVATION_BYTES,
            max_file_bytes=_MAX_OBSERVATION_BYTES,
        ),
    )
    if os.path.lexists(observation_path):
        state = observation_path.lstat()
        if not stat.S_ISREG(state.st_mode) or state.st_size > _MAX_OBSERVATION_BYTES:
            raise BenchmarkRunError("failed worker left an invalid observation output")
    if not os.path.lexists(measured_workspace):
        if expected_workspace is not None:
            raise BenchmarkRunError("generated fixture topology changed")
        return
    _snapshot_tree(
        measured_workspace,
        limits=workspace_limits,
        expected=expected_workspace,
    )


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
    shutil.copytree(fixture.workspace.root, destination, symlinks=True)
    return destination


def _snapshot_tree(
    root: Path,
    *,
    limits: _TreeLimits,
    expected: _TreeSnapshot | None = None,
) -> _TreeSnapshot:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(root, flags)
    except OSError as error:
        raise BenchmarkRunError("generated fixture topology root is unsafe") from error
    try:
        root_state = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_state.st_mode):
            raise BenchmarkRunError("generated fixture topology root must be a directory")
        metadata: dict[str, _TreeMetadata] = {".": _tree_metadata(root_state)}
        children: _TreeChildren = {}
        declared_bytes = [0]
        remaining_entries = [limits.max_entries - 1]
        if remaining_entries[0] < 0:
            raise BenchmarkRunError(
                "generated fixture topology entries exceed the validation bound"
            )
        _preflight_directory(
            root_descriptor,
            "",
            metadata,
            limits,
            declared_bytes,
            remaining_entries,
            children,
        )
        if expected is not None and metadata != {
            relative: _entry_metadata(entry) for relative, entry in expected.items()
        }:
            raise BenchmarkRunError("generated fixture topology changed")
        snapshot = {".": _directory_entry(root_descriptor, root_state)}
        _snapshot_directory(root_descriptor, "", snapshot, metadata, children)
        if expected is not None and snapshot != expected:
            raise BenchmarkRunError("generated fixture topology changed")
        return snapshot
    finally:
        os.close(root_descriptor)


def _snapshot_directory(
    directory_descriptor: int,
    relative_parent: str,
    snapshot: _TreeSnapshot,
    metadata: dict[str, _TreeMetadata],
    children: _TreeChildren,
) -> None:
    expected_names = children[relative_parent]
    names = _bounded_directory_names(directory_descriptor, len(expected_names))
    if tuple(names) != expected_names:
        raise BenchmarkRunError("generated fixture topology changed during validation")
    for name in names:
        relative = name if not relative_parent else f"{relative_parent}/{name}"
        state = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if _tree_metadata(state) != metadata[relative]:
            raise BenchmarkRunError("generated fixture topology changed during validation")
        if stat.S_ISLNK(state.st_mode):
            raise BenchmarkRunError("generated fixture topology contains a symlink")
        if stat.S_ISDIR(state.st_mode):
            child_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            child_descriptor = os.open(name, child_flags, dir_fd=directory_descriptor)
            try:
                descriptor_state = os.fstat(child_descriptor)
                _require_same_inode(state, descriptor_state)
                snapshot[relative] = _directory_entry(child_descriptor, descriptor_state)
                _snapshot_directory(child_descriptor, relative, snapshot, metadata, children)
            finally:
                os.close(child_descriptor)
            continue
        if stat.S_ISREG(state.st_mode):
            file_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            try:
                descriptor_state = os.fstat(file_descriptor)
                _require_same_inode(state, descriptor_state)
                snapshot[relative] = _file_entry(file_descriptor, descriptor_state)
            finally:
                os.close(file_descriptor)
            continue
        raise BenchmarkRunError("generated fixture topology contains a special filesystem entry")


def _preflight_directory(
    directory_descriptor: int,
    relative_parent: str,
    metadata: dict[str, _TreeMetadata],
    limits: _TreeLimits,
    declared_bytes: list[int],
    remaining_entries: list[int],
    children: _TreeChildren,
) -> None:
    names = _bounded_directory_names(directory_descriptor, remaining_entries[0])
    remaining_entries[0] -= len(names)
    children[relative_parent] = tuple(names)
    for name in names:
        relative = name if not relative_parent else f"{relative_parent}/{name}"
        state = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(state.st_mode):
            raise BenchmarkRunError("generated fixture topology contains a symlink")
        if stat.S_ISDIR(state.st_mode):
            kind: Literal["directory", "file"] = "directory"
        elif stat.S_ISREG(state.st_mode):
            kind = "file"
            if state.st_size > limits.max_file_bytes:
                raise BenchmarkRunError(
                    "generated fixture topology file exceeds the validation bound"
                )
            declared_bytes[0] += state.st_size
            if declared_bytes[0] > limits.max_total_declared_bytes:
                raise BenchmarkRunError(
                    "generated fixture topology bytes exceed the validation bound"
                )
        else:
            raise BenchmarkRunError(
                "generated fixture topology contains a special filesystem entry"
            )
        metadata[relative] = _tree_metadata(state, kind=kind)
        if len(metadata) > limits.max_entries:
            raise BenchmarkRunError(
                "generated fixture topology entries exceed the validation bound"
            )
        if kind == "directory":
            child_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            try:
                _require_same_inode(state, os.fstat(child_descriptor))
                _preflight_directory(
                    child_descriptor,
                    relative,
                    metadata,
                    limits,
                    declared_bytes,
                    remaining_entries,
                    children,
                )
            finally:
                os.close(child_descriptor)


def _bounded_directory_names(directory_descriptor: int, maximum: int) -> list[str]:
    names: list[str] = []
    with os.scandir(directory_descriptor) as iterator:
        for entry in iterator:
            if len(names) >= maximum:
                raise BenchmarkRunError(
                    "generated fixture topology entries exceed the validation bound"
                )
            names.append(entry.name)
    names.sort()
    return names


def _tree_metadata(
    state: os.stat_result,
    *,
    kind: Literal["directory", "file"] | None = None,
) -> _TreeMetadata:
    if kind is None:
        kind = "directory" if stat.S_ISDIR(state.st_mode) else "file"
    return (
        kind,
        stat.S_IMODE(state.st_mode),
        0 if kind == "directory" else state.st_size,
        state.st_mtime_ns,
        state.st_uid,
        state.st_gid,
        state.st_nlink,
    )


def _entry_metadata(entry: _TreeEntry) -> _TreeMetadata:
    return (
        entry.kind,
        entry.mode,
        entry.size,
        entry.mtime_ns,
        entry.user_id,
        entry.group_id,
        entry.link_count,
    )


def _limits_for_snapshot(snapshot: _TreeSnapshot | None) -> _TreeLimits:
    if snapshot is None:
        raise BenchmarkRunError("generated fixture baseline is unavailable")
    sizes = tuple(entry.size for entry in snapshot.values() if entry.kind == "file")
    return _TreeLimits(
        max_entries=len(snapshot),
        max_total_declared_bytes=sum(sizes),
        max_file_bytes=max(sizes, default=0),
    )


def _fixture_tree_limits(fixture: GeneratedFixture) -> _TreeLimits:
    profile = fixture.profile
    return _TreeLimits(
        max_entries=4 * profile.document_count + 256,
        max_total_declared_bytes=2 * fixture.exact_workspace_bytes,
        max_file_bytes=max(profile.target_wiki_bytes, 4 * profile.source_characters, 1024 * 1024),
    )


def _mutation_tree_limits(fixture: GeneratedFixture) -> _TreeLimits:
    profile = fixture.profile
    return _TreeLimits(
        max_entries=8 * profile.document_count + 512,
        max_total_declared_bytes=4 * fixture.exact_workspace_bytes + 4 * profile.source_characters,
        max_file_bytes=max(profile.target_wiki_bytes, 4 * profile.source_characters, 1024 * 1024),
    )


def _initialization_tree_limits() -> _TreeLimits:
    return _TreeLimits(
        max_entries=256,
        max_total_declared_bytes=4 * 1024 * 1024,
        max_file_bytes=1024 * 1024,
    )


def _directory_entry(descriptor: int, state: os.stat_result) -> _TreeEntry:
    return _TreeEntry(
        kind="directory",
        mode=stat.S_IMODE(state.st_mode),
        size=0,
        mtime_ns=state.st_mtime_ns,
        user_id=state.st_uid,
        group_id=state.st_gid,
        link_count=state.st_nlink,
        content_sha256=None,
        xattrs=_descriptor_xattrs(descriptor),
    )


def _file_entry(descriptor: int, state: os.stat_result) -> _TreeEntry:
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    return _TreeEntry(
        kind="file",
        mode=stat.S_IMODE(state.st_mode),
        size=state.st_size,
        mtime_ns=state.st_mtime_ns,
        user_id=state.st_uid,
        group_id=state.st_gid,
        link_count=state.st_nlink,
        content_sha256=digest.hexdigest(),
        xattrs=_descriptor_xattrs(descriptor),
    )


def _descriptor_xattrs(descriptor: int) -> tuple[tuple[str, str], ...]:
    list_xattrs = getattr(os, "listxattr", None)
    get_xattr = getattr(os, "getxattr", None)
    if list_xattrs is None or get_xattr is None:
        return ()
    try:
        names = sorted(list_xattrs(descriptor))
        return tuple(
            (name, hashlib.sha256(get_xattr(descriptor, name)).hexdigest()) for name in names
        )
    except OSError as error:
        raise BenchmarkRunError("generated fixture metadata could not be validated") from error


def _require_same_inode(path_state: os.stat_result, descriptor_state: os.stat_result) -> None:
    if (path_state.st_dev, path_state.st_ino) != (descriptor_state.st_dev, descriptor_state.st_ino):
        raise BenchmarkRunError("generated fixture topology changed during validation")


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
