# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import getpass
import json
import os
import platform
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

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


def test_evidence_writer_refuses_an_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "evidence.json"
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_evidence(destination, evidence_record())

    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_atomic_write_cleans_owned_temporary_file_after_link_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "evidence.json"

    def fail_link(_source: Path, _destination: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", fail_link)

    with pytest.raises(OSError, match="injected link failure"):
        write_evidence(destination, evidence_record())

    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))


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

    def run_stat(command: list[str | Path], **options: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, stdout="apfs\n", stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", run_stat)

    environment = collect_environment(tmp_path)

    assert environment.filesystem_type == "apfs"
    assert calls == [
        (
            ["stat", "-f", "%T", tmp_path],
            {"capture_output": True, "check": False, "text": True, "timeout": 5},
        )
    ]


@pytest.mark.parametrize("stdout", ["", "one\ntwo\n", "x" * 65 + "\n"])
def test_environment_probe_rejects_unbounded_or_incomplete_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    def run_stat(command: list[str | Path], **_options: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "run", run_stat)

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


def test_atomic_writer_cleans_owned_temporary_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "preview.md"

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise OSError("injected write failure")

    monkeypatch.setattr(os, "write", fail_write)

    with pytest.raises(OSError, match="injected write failure"):
        write_new_text(destination, "content")

    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))


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
    assert not list(tmp_path.glob("*.partial"))


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

    replacements = list(tmp_path.glob("*.partial"))
    assert len(replacements) == 1
    assert replacements[0].read_text(encoding="utf-8") == "actor-owned\n"


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
