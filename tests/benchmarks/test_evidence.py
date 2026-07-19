# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import getpass
import json
import os
import platform
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

import benchmarks.evidence as evidence_module
from benchmarks.contracts import SampleObservation, ScenarioDisposition, ScenarioName
from benchmarks.evidence import (
    collect_environment,
    load_evidence,
    materialized_bytes,
    nearest_rank_p95,
    summarize_samples,
    write_evidence,
    write_new_text,
)
from tests.benchmarks.factories import evidence_record

_preserve_temporary = cast(
    Callable[[Path, tuple[int, int]], bool], vars(evidence_module)["_preserve_temporary"]
)


def test_summary_uses_median_nearest_rank_p95_and_stable_output() -> None:
    observations = tuple(
        SampleObservation(
            scenario=ScenarioName.STATUS,
            profile="smoke",
            duration_ns=value,
            output_sha256="a" * 64,
        )
        for value in (100, 200, 300, 400, 500, 600, 700)
    )

    result = summarize_samples(observations, target=350)

    assert result.median_ns == 400
    assert result.p95_ns == 700
    assert result.disposition is ScenarioDisposition.TARGET_MISSED


def test_environment_record_contains_no_identity_or_paths(tmp_path: Path) -> None:
    serialized = collect_environment(tmp_path).model_dump_json()
    if username := getpass.getuser():
        assert username not in serialized
    if hostname := platform.node():
        assert hostname not in serialized
    assert str(tmp_path) not in serialized
    assert "environment" not in serialized.casefold()


@pytest.mark.parametrize(
    "runner_image",
    [
        "ubuntu/24",
        r"C:\runner\image",
        "ubuntu\nprivate",
        "ubuntu\tprivate",
        "x" * 65,
        "ubuntu 24",
        "",
        "hendrik",
        "build-host-01",
        "runner_image.v1",
        "macos-15",
    ],
)
def test_environment_rejects_unsafe_runner_image_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_image: str,
) -> None:
    monkeypatch.setenv("ImageOS", runner_image)

    assert collect_environment(tmp_path).runner_image is None


def test_environment_rejects_runner_image_containing_the_benchmark_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ImageOS", f"image-{tmp_path}")

    environment = collect_environment(tmp_path)

    assert environment.runner_image is None
    assert str(tmp_path) not in environment.model_dump_json()


@pytest.mark.parametrize("runner_image", ["ubuntu24", "macos15"])
def test_environment_accepts_recognized_phase_one_runner_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_image: str,
) -> None:
    monkeypatch.setenv("ImageOS", runner_image)

    assert collect_environment(tmp_path).runner_image == runner_image


def test_evidence_writer_refuses_an_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "evidence.json"
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_evidence(destination, evidence_record())

    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_atomic_write_retains_owner_only_temporary_after_link_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "evidence.json"

    def fail_link(_source: Path, _destination: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", fail_link)

    with pytest.raises(OSError, match="injected link failure"):
        write_evidence(destination, evidence_record())

    assert not destination.exists()
    _assert_owner_only_partials(tmp_path, expected_count=1)


def test_materialized_bytes_counts_a_hard_linked_inode_once(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x" * 8192)
    before = materialized_bytes(tmp_path)

    os.link(payload, tmp_path / "payload-link.bin")

    assert materialized_bytes(tmp_path) == before


def test_nearest_rank_p95_uses_ceiling_rank_and_rejects_empty_input() -> None:
    assert nearest_rank_p95(tuple(range(1, 21))) == 19
    with pytest.raises(ValueError, match="at least one"):
        nearest_rank_p95(())


def test_summary_requires_one_scenario_profile_and_output_digest() -> None:
    observations = list(_observations(ScenarioName.STATUS, 7))

    for field, value, message in (
        ("scenario", ScenarioName.LINT, "one scenario"),
        ("profile", "small", "one profile"),
        ("output_sha256", "b" * 64, "one output digest"),
    ):
        mixed = observations.copy()
        mixed[-1] = mixed[-1].model_copy(update={field: value})
        with pytest.raises(ValueError, match=message):
            summarize_samples(mixed, target=1_000)


@pytest.mark.parametrize(
    ("scenario", "sample_count", "expected_count"),
    [
        (ScenarioName.STATUS, 6, 7),
        (ScenarioName.COMMIT, 4, 5),
    ],
)
def test_summary_enforces_exact_measurement_repetitions(
    scenario: ScenarioName, sample_count: int, expected_count: int
) -> None:
    with pytest.raises(ValueError, match=rf"exactly {expected_count}"):
        summarize_samples(_observations(scenario, sample_count), target=1_000)


def test_summary_accepts_one_correctness_sample_and_maximizes_checkpoints() -> None:
    correctness = summarize_samples(
        _observations(ScenarioName.COMMIT, 1), target=1_000, correctness_only=True
    )
    observations = tuple(
        SampleObservation(
            scenario=ScenarioName.COMMIT,
            profile="smoke",
            duration_ns=value,
            output_sha256="a" * 64,
            checkpoint_bytes={"prepared": value * 10, "cleaned": value},
        )
        for value in (1, 2, 3, 4, 5)
    )

    measured = summarize_samples(observations, target=1_000)

    assert correctness.samples_ns == (1,)
    assert measured.checkpoint_bytes == {"prepared": 50, "cleaned": 5}


def test_environment_probe_uses_bounded_explicit_darwin_stat_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str | Path], dict[str, Any]]] = []

    def open_stat(command: list[str | Path], **options: Any) -> _CompletedStat:
        calls.append((command, options))
        return _CompletedStat(b"apfs\n")

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "Popen", open_stat)

    environment = collect_environment(tmp_path)

    assert environment.filesystem_type == "apfs"
    assert calls == [
        (
            ["stat", "-f", "%T", tmp_path],
            {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL},
        )
    ]


@pytest.mark.parametrize("stdout", ["", "one\ntwo\n", "x" * 65 + "\n"])
def test_environment_probe_rejects_unbounded_or_incomplete_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    def open_stat(_command: list[str | Path], **_options: Any) -> _CompletedStat:
        return _CompletedStat(stdout.encode())

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen", open_stat)

    assert collect_environment(tmp_path).filesystem_type is None


def test_evidence_round_trips_as_canonical_owner_only_json(tmp_path: Path) -> None:
    destination = tmp_path / "evidence.json"
    evidence = evidence_record()

    write_evidence(destination, evidence)

    expected = json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    assert destination.read_text(encoding="utf-8") == expected
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert load_evidence(destination) == evidence


def test_evidence_loader_rejects_unknown_schema_fields(tmp_path: Path) -> None:
    destination = tmp_path / "invalid.json"
    values = evidence_record().model_dump(mode="json")
    values["private_path"] = str(tmp_path)
    destination.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(ValidationError, match="private_path"):
        load_evidence(destination)


def test_text_writer_publishes_exact_utf8_and_refuses_dangling_symlink(tmp_path: Path) -> None:
    destination = tmp_path / "preview.md"
    write_new_text(destination, "capacity: café\n")

    assert destination.read_bytes() == "capacity: café\n".encode()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    dangling = tmp_path / "dangling.md"
    dangling.symlink_to(tmp_path / "missing.md")
    with pytest.raises(FileExistsError):
        write_new_text(dangling, "replacement")
    assert dangling.is_symlink()


def test_atomic_writer_completes_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    original_write = os.write
    calls = 0

    def write_short(descriptor: int, content: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        return original_write(descriptor, content[:3])

    monkeypatch.setattr(os, "write", write_short)

    write_new_text(destination, "abcdefghij")

    assert calls > 1
    assert destination.read_text(encoding="utf-8") == "abcdefghij"


def test_atomic_writer_retains_owner_only_temporary_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise OSError("injected write failure")

    monkeypatch.setattr(os, "write", fail_write)

    with pytest.raises(OSError, match="injected write failure"):
        write_new_text(destination, "content")

    assert not destination.exists()
    _assert_owner_only_partials(tmp_path, expected_count=1)


def test_atomic_writer_preserves_competing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    original_link = os.link

    def publish_competitor(source: Path, target: Path) -> None:
        target.write_text("competitor\n", encoding="utf-8")
        original_link(source, target)

    monkeypatch.setattr(os, "link", publish_competitor)

    with pytest.raises(FileExistsError):
        write_new_text(destination, "ours\n")

    assert destination.read_text(encoding="utf-8") == "competitor\n"
    _assert_owner_only_partials(tmp_path, expected_count=1)


def test_atomic_writer_never_deletes_an_unowned_temporary_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"

    def replace_temporary_then_fail(source: Path, _target: Path) -> None:
        source.unlink()
        source.write_text("actor-owned\n", encoding="utf-8")
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "link", replace_temporary_then_fail)

    with pytest.raises(OSError, match="injected publication failure"):
        write_new_text(destination, "ours\n")

    assert "actor-owned\n" in {
        item.read_text(encoding="utf-8") for item in tmp_path.rglob("*") if item.is_file()
    }


def test_atomic_writer_rejects_an_unowned_inode_published_during_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    actor_content = "actor-owned\n"
    original_link = os.link

    def replace_source_then_publish(source: Path, target: Path) -> None:
        source.unlink()
        source.write_text(actor_content, encoding="utf-8")
        original_link(source, target)

    monkeypatch.setattr(os, "link", replace_source_then_publish)

    with pytest.raises(OSError, match="changed during publication"):
        write_new_text(destination, "ours\n")

    assert destination.read_text(encoding="utf-8") == actor_content


def test_atomic_writer_never_uses_overwriting_rename_during_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    actor_content = "actor-owned\n"
    original_rename = os.rename
    replacement_installed = False

    def replace_then_quarantine(source: Path, target: Path) -> None:
        nonlocal replacement_installed
        source.unlink()
        source.write_text(actor_content, encoding="utf-8")
        replacement_installed = True
        original_rename(source, target)

    def fail_link(_source: Path, _target: Path) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, "link", fail_link)
    monkeypatch.setattr(os, "rename", replace_then_quarantine)

    with pytest.raises(OSError, match="injected publication failure"):
        write_new_text(destination, "ours\n")

    assert not replacement_installed
    assert actor_content not in {
        item.read_text(encoding="utf-8") for item in tmp_path.rglob("*") if item.is_file()
    }
    _assert_owner_only_partials(tmp_path, expected_count=1)


def test_owned_cleanup_conservatively_preserves_the_quarantined_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / ".evidence.partial"
    temporary.write_text("ours", encoding="utf-8")
    metadata = temporary.stat()
    identity = metadata.st_dev, metadata.st_ino
    original_unlink = Path.unlink
    swapped = False

    def racing_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal swapped
        if path.name == "candidate" and not swapped:
            swapped = True
            original_unlink(path)
            path.write_text("actor-owned", encoding="utf-8")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    preserved_owned = _preserve_temporary(temporary, identity)

    assert preserved_owned
    assert not swapped
    retained = [item for item in tmp_path.rglob("*") if item.is_file()]
    assert len(retained) == 2
    assert {item.read_text(encoding="utf-8") for item in retained} == {"ours"}
    assert len({(item.stat().st_dev, item.stat().st_ino) for item in retained}) == 1


def test_quarantine_transition_never_overwrites_an_actor_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / ".evidence.partial"
    temporary.write_text("ours", encoding="utf-8")
    metadata = temporary.stat()
    identity = metadata.st_dev, metadata.st_ino
    original_mkdtemp = tempfile.mkdtemp

    def plant_candidate(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | os.PathLike[str] | None = None,
    ) -> str:
        quarantine = Path(original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir))
        (quarantine / "candidate").write_text("actor-owned", encoding="utf-8")
        return str(quarantine)

    monkeypatch.setattr(tempfile, "mkdtemp", plant_candidate)

    preserved_owned = _preserve_temporary(temporary, identity)

    assert not preserved_owned
    assert temporary.read_text(encoding="utf-8") == "ours"
    assert "actor-owned" in {
        item.read_text(encoding="utf-8") for item in tmp_path.rglob("*") if item.is_file()
    }


def test_failed_quarantine_transition_never_removes_an_actor_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / ".evidence.partial"
    temporary.write_text("ours", encoding="utf-8")
    metadata = temporary.stat()
    identity = metadata.st_dev, metadata.st_ino
    original_mkdtemp = tempfile.mkdtemp
    original_rename = os.rename
    quarantines: list[Path] = []
    actor_identities: list[tuple[int, int]] = []

    def record_quarantine(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | os.PathLike[str] | None = None,
    ) -> str:
        quarantine = Path(original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir))
        original_rename(quarantine, quarantine.with_name(f"{quarantine.name}.parked"))
        quarantine.mkdir(mode=0o700)
        quarantines.append(quarantine)
        metadata = quarantine.stat()
        actor_identities.append((metadata.st_dev, metadata.st_ino))
        return str(quarantine)

    def fail_transition(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("injected transition failure")

    monkeypatch.setattr(tempfile, "mkdtemp", record_quarantine)
    monkeypatch.setattr(os, "rename", fail_transition)
    monkeypatch.setattr(os, "link", fail_transition)

    preserved_owned = _preserve_temporary(temporary, identity)

    assert not preserved_owned
    assert quarantines[0].is_dir()
    metadata = quarantines[0].stat()
    assert (metadata.st_dev, metadata.st_ino) == actor_identities[0]
    assert temporary.read_text(encoding="utf-8") == "ours"


def test_owned_cleanup_preserves_replacement_after_anchored_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / ".evidence.partial"
    temporary.write_text("ours", encoding="utf-8")
    metadata = temporary.stat()
    identity = metadata.st_dev, metadata.st_ino
    original_open = os.open
    original_unlink = Path.unlink
    replaced = False

    def open_then_replace(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "candidate" and dir_fd is not None and not replaced:
            candidate = next(tmp_path.rglob("candidate"))
            original_unlink(candidate)
            candidate.write_text("actor-owned", encoding="utf-8")
            replaced = True
        return descriptor

    monkeypatch.setattr(os, "open", open_then_replace)

    preserved_owned = _preserve_temporary(temporary, identity)

    assert not preserved_owned
    assert replaced
    assert "actor-owned" in {
        item.read_text(encoding="utf-8") for item in tmp_path.rglob("*") if item.is_file()
    }


def test_owned_cleanup_never_deletes_at_the_final_unlinkat_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / ".evidence.partial"
    temporary.write_text("ours", encoding="utf-8")
    metadata = temporary.stat()
    identity = metadata.st_dev, metadata.st_ino
    original_unlink = os.unlink
    swapped = False

    def racing_unlink(
        path: str | bytes | Path,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if path == "candidate" and dir_fd is not None and not swapped:
            swapped = True
            original_unlink(path, dir_fd=dir_fd)
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(descriptor, b"actor-owned")
            finally:
                os.close(descriptor)
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", racing_unlink)

    preserved_owned = _preserve_temporary(temporary, identity)

    assert preserved_owned
    assert not swapped
    retained = [item for item in tmp_path.rglob("*") if item.is_file()]
    assert len(retained) == 2
    assert {item.read_text(encoding="utf-8") for item in retained} == {"ours"}
    assert len({(item.stat().st_dev, item.stat().st_ino) for item in retained}) == 1


def test_atomic_writer_retains_temporary_after_initial_fstat_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    original_fstat = os.fstat
    calls = 0

    def fail_first_fstat(descriptor: int) -> os.stat_result:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(os, "fstat", fail_first_fstat)

    with pytest.raises(OSError, match="injected fstat failure"):
        write_new_text(destination, "ours\n")

    assert not destination.exists()
    _assert_owner_only_partials(tmp_path, expected_count=1)


def test_atomic_writer_does_not_retry_an_ambiguous_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"
    original_close = os.close
    close_calls = 0

    def close_then_fail(descriptor: int) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(descriptor)
        if close_calls == 1:
            raise OSError("injected close failure")

    def report_cleaned(_path: Path, _identity: tuple[int, int]) -> bool:
        return True

    def skip_parent_sync(_path: Path) -> None:
        return None

    monkeypatch.setattr(os, "close", close_then_fail)
    monkeypatch.setattr(evidence_module, "_preserve_temporary", report_cleaned)
    monkeypatch.setattr(evidence_module, "_fsync_parent", skip_parent_sync)

    with pytest.raises(OSError, match="injected close failure"):
        write_new_text(destination, "ours\n")

    assert close_calls == 1
    assert not destination.exists()


def test_environment_probe_uses_a_bounded_pipe_instead_of_buffered_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_descriptor, write_descriptor = os.pipe()
    os.write(write_descriptor, b"apfs\n")
    os.close(write_descriptor)

    class CompletedStat:
        def __init__(self) -> None:
            self.stdout = os.fdopen(read_descriptor, "rb", buffering=0)
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    process = CompletedStat()

    def open_stat(*_arguments: Any, **_options: Any) -> CompletedStat:
        return process

    def reject_buffered_capture(*_arguments: Any, **_options: Any) -> None:
        raise AssertionError("subprocess.run must not buffer stat output")

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "Popen", open_stat)
    monkeypatch.setattr(subprocess, "run", reject_buffered_capture)

    assert collect_environment(tmp_path).filesystem_type == "apfs"
    assert process.stdout.closed


def _observations(scenario: ScenarioName, count: int) -> tuple[SampleObservation, ...]:
    return tuple(
        SampleObservation(
            scenario=scenario,
            profile="smoke",
            duration_ns=value,
            output_sha256="a" * 64,
        )
        for value in range(1, count + 1)
    )


class _CompletedStat:
    def __init__(self, output: bytes) -> None:
        read_descriptor, write_descriptor = os.pipe()
        os.write(write_descriptor, output)
        os.close(write_descriptor)
        self.stdout = os.fdopen(read_descriptor, "rb", buffering=0)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def _assert_owner_only_partials(root: Path, *, expected_count: int) -> None:
    partials = list(root.glob("*.partial"))
    assert len(partials) == expected_count
    assert all(stat.S_IMODE(partial.stat().st_mode) == 0o600 for partial in partials)
