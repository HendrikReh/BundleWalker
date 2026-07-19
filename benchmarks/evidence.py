# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import platform
import secrets
import selectors
import stat
import subprocess
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel

from benchmarks.contracts import (
    CheckpointBytes,
    CheckpointName,
    EnvironmentRecord,
    EvidenceRecord,
    SampleObservation,
    ScenarioDisposition,
    ScenarioEvidence,
    ScenarioName,
)

_READ_ONLY_SCENARIOS = frozenset(
    {
        ScenarioName.INITIALIZE,
        ScenarioName.STATUS,
        ScenarioName.LIST_CONCEPTS,
        ScenarioName.READ_CONCEPT,
        ScenarioName.SEARCH_PRESENT,
        ScenarioName.SEARCH_ABSENT,
        ScenarioName.LINT,
        ScenarioName.MCP_STARTUP,
    }
)
_STAT_TIMEOUT_SECONDS = 5
_MAX_FILESYSTEM_TYPE_CHARACTERS = 64
_TEMPORARY_CREATION_ATTEMPTS = 32


def nearest_rank_p95(samples: Sequence[int]) -> int:
    if not samples:
        raise ValueError("p95 requires at least one sample")
    sorted_samples = sorted(samples)
    return sorted_samples[(95 * len(sorted_samples) + 99) // 100 - 1]


def summarize_samples(
    observations: Sequence[SampleObservation],
    target: int,
    *,
    correctness_only: bool = False,
) -> ScenarioEvidence:
    if not observations:
        raise ValueError("sample summary requires observations")

    scenarios = {observation.scenario for observation in observations}
    profiles = {observation.profile for observation in observations}
    output_digests = {observation.output_sha256 for observation in observations}
    if len(scenarios) != 1:
        raise ValueError("sample group must contain exactly one scenario")
    if len(profiles) != 1:
        raise ValueError("sample group must contain exactly one profile")
    if len(output_digests) != 1:
        raise ValueError("sample group must contain exactly one output digest")

    scenario = next(iter(scenarios))
    expected_count = 1 if correctness_only else 7 if scenario in _READ_ONLY_SCENARIOS else 5
    if len(observations) != expected_count:
        raise ValueError(f"sample group requires exactly {expected_count} observations")

    samples = tuple(observation.duration_ns for observation in observations)
    sorted_samples = sorted(samples)
    median = sorted_samples[len(sorted_samples) // 2]
    checkpoints: dict[CheckpointName, CheckpointBytes] = {}
    for observation in observations:
        for checkpoint, byte_count in observation.checkpoint_bytes.items():
            checkpoints[checkpoint] = max(checkpoints.get(checkpoint, 0), byte_count)

    return ScenarioEvidence(
        scenario=scenario,
        profile=next(iter(profiles)),
        target_ns=target,
        samples_ns=samples,
        median_ns=median,
        p95_ns=nearest_rank_p95(samples),
        output_sha256=next(iter(output_digests)),
        checkpoint_bytes=checkpoints,
        disposition=(
            ScenarioDisposition.TARGET_MISSED if median > target else ScenarioDisposition.PASS
        ),
    )


def collect_environment(root: Path) -> EnvironmentRecord:
    return EnvironmentRecord(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        os_name=platform.system(),
        os_release=platform.release(),
        architecture=platform.machine(),
        logical_cpu_count=os.cpu_count(),
        total_memory_bytes=_portable_total_memory(),
        runner_image=os.environ.get("ImageOS"),  # noqa: SIM112 - GitHub's documented key
        filesystem_type=_portable_filesystem_type(root),
    )


def write_new_json(path: Path, model: BaseModel) -> None:
    content = json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    write_new_text(path, content)


def write_new_text(path: Path, content: str) -> None:
    _write_new_bytes(path, content.encode("utf-8"))


def write_evidence(path: Path, evidence: EvidenceRecord) -> None:
    write_new_json(path, evidence)


def load_evidence(path: Path) -> EvidenceRecord:
    return EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))


def materialized_bytes(root: Path) -> int:
    paths = (root, *root.rglob("*"))
    total = 0
    counted_inodes: set[tuple[int, int]] = set()
    for path in paths:
        metadata = path.lstat()
        identity = metadata.st_dev, metadata.st_ino
        if identity in counted_inodes:
            continue
        counted_inodes.add(identity)
        blocks = getattr(metadata, "st_blocks", None)
        total += blocks * 512 if isinstance(blocks, int) else metadata.st_size
    return total


def _portable_total_memory() -> int | None:
    if platform.system() not in {"Darwin", "Linux"}:
        return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    total = page_size * page_count
    return total if total > 0 else None


def _portable_filesystem_type(root: Path) -> str | None:
    system = platform.system()
    if system == "Darwin":
        command = ["stat", "-f", "%T", root]
    elif system == "Linux":
        command = ["stat", "-f", "-c", "%T", "--", root]
    else:
        return None

    output = _bounded_stat_output(command)
    if output is None:
        return None
    lines = output.splitlines()
    if len(lines) != 1:
        return None
    filesystem_type = lines[0]
    if not 1 <= len(filesystem_type) <= _MAX_FILESYSTEM_TYPE_CHARACTERS:
        return None
    if os.fspath(root) in filesystem_type:
        return None
    return filesystem_type


def _write_new_bytes(path: Path, content: bytes) -> None:
    if os.path.lexists(path):
        raise FileExistsError(path)

    temporary, descriptor = _create_temporary_sibling(path)
    identity: tuple[int, int] | None = None
    try:
        metadata = os.fstat(descriptor)
        identity = metadata.st_dev, metadata.st_ino
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("temporary evidence output is not a regular file")
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        descriptor_to_close = descriptor
        descriptor = -1
        os.close(descriptor_to_close)
        _require_owned_path(temporary, identity)
        os.link(temporary, path)
        _require_owned_path(path, identity, message="evidence output changed during publication")
    except BaseException:
        if identity is None and descriptor >= 0:
            with suppress(OSError):
                metadata = os.fstat(descriptor)
                identity = metadata.st_dev, metadata.st_ino
        if descriptor >= 0:
            descriptor_to_close = descriptor
            descriptor = -1
            with suppress(OSError):
                os.close(descriptor_to_close)
        if identity is not None:
            _unlink_owned(temporary, identity)
            with suppress(OSError):
                _fsync_parent(path)
        raise

    assert identity is not None
    removed = _unlink_owned(temporary, identity)
    if not removed:
        raise OSError("temporary evidence output changed during publication")
    _fsync_parent(path)


def _create_temporary_sibling(path: Path) -> tuple[Path, int]:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    for _attempt in range(_TEMPORARY_CREATION_ATTEMPTS):
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.partial")
        try:
            return temporary, os.open(temporary, flags, 0o600)
        except FileExistsError:
            continue
    raise FileExistsError("could not reserve a temporary evidence output")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise OSError("evidence write made no progress")
        remaining = remaining[written:]


def _require_owned_path(
    path: Path,
    identity: tuple[int, int],
    *,
    message: str = "temporary evidence output changed during creation",
) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != identity:
        raise OSError(message)


def _unlink_owned(path: Path, identity: tuple[int, int]) -> bool:
    quarantine = Path(tempfile.mkdtemp(prefix=f".{path.name}.cleanup-", dir=path.parent))
    candidate = quarantine / "candidate"
    try:
        try:
            os.rename(path, candidate)
        except FileNotFoundError:
            return False

        try:
            _require_owned_path(candidate, identity)
        except OSError:
            try:
                os.link(candidate, path)
            except OSError:
                return False
            candidate.unlink()
            return False

        candidate.unlink()
        return True
    finally:
        with suppress(OSError):
            quarantine.rmdir()


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _bounded_stat_output(command: list[str | Path]) -> str | None:
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + _STAT_TIMEOUT_SECONDS
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:
            return None
        selector.register(process.stdout, selectors.EVENT_READ)
        captured = bytearray()
        while len(captured) <= _MAX_FILESYSTEM_TYPE_CHARACTERS:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(command, _STAT_TIMEOUT_SECONDS)
            chunk = os.read(process.stdout.fileno(), 66 - len(captured))
            if not chunk:
                break
            captured.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, _STAT_TIMEOUT_SECONDS)
        return_code = process.wait(timeout=remaining)
        if return_code != 0 or len(captured) > 65:
            return None
        try:
            return captured.decode("utf-8")
        except UnicodeDecodeError:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        selector.close()
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    with suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=1)
