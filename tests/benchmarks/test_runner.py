# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, cast

import pytest

import benchmarks.__main__ as benchmark_cli
import benchmarks.runner as runner_module
from benchmarks.contracts import ScenarioDisposition, ScenarioName
from benchmarks.evidence import load_evidence, write_evidence
from benchmarks.fixtures import generate_fixture
from benchmarks.profiles import PROFILES
from benchmarks.runner import BenchmarkRunError, RunConfig, run_benchmarks
from tests.benchmarks.factories import evidence_record

PROJECT_ROOT = Path(__file__).parents[2]


def test_correctness_only_runner_writes_one_sample_per_scenario(tmp_path: Path) -> None:
    evidence = run_benchmarks(
        RunConfig(
            profiles=(PROFILES["smoke"],),
            output=tmp_path / "evidence.json",
            work_root=tmp_path / "work",
            run_id="test-smoke",
            correctness_only=True,
        )
    )

    assert evidence.disposition is ScenarioDisposition.PASS
    assert {len(item.samples_ns) for item in evidence.scenarios} == {1}
    assert load_evidence(tmp_path / "evidence.json") == evidence


def test_cli_rejects_duplicate_profiles_as_argparse_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "--profiles",
            "smoke,smoke",
            "--output",
            str(tmp_path / "evidence.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert str(tmp_path) not in result.stderr


@pytest.mark.parametrize("residue", ["empty_directory", "symlink", "fifo"])
def test_read_only_runner_rejects_full_topology_residue_without_reading_external_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    residue: str,
) -> None:
    external = tmp_path / "external-target"
    external.write_text("must-not-be-read-or-changed", encoding="ascii")
    _replace_worker_with_residue_process(monkeypatch, residue=residue, external=external)
    output = tmp_path / "evidence.json"

    with pytest.raises(BenchmarkRunError, match="topology"):
        run_benchmarks(
            RunConfig(
                profiles=(PROFILES["smoke"],),
                output=output,
                work_root=tmp_path / "work",
                run_id=f"residue-{residue}",
                correctness_only=True,
            )
        )

    assert external.read_text(encoding="ascii") == "must-not-be-read-or-changed"
    assert not output.exists()


def _replace_worker_with_residue_process(
    monkeypatch: pytest.MonkeyPatch,
    *,
    residue: str,
    external: Path,
) -> None:
    original_popen = subprocess.Popen
    script = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path

        from benchmarks.contracts import SampleObservation, ScenarioName
        from benchmarks.evidence import write_new_json

        scenario = ScenarioName(sys.argv[1])
        workspace = Path(sys.argv[2])
        profile = None if sys.argv[3] == "-" else sys.argv[3]
        output = Path(sys.argv[4])
        residue = sys.argv[5]
        external = Path(sys.argv[6])
        if scenario is ScenarioName.STATUS:
            if residue == "empty_directory":
                (workspace / "unexpected-empty").mkdir()
            elif residue == "symlink":
                (workspace / "unexpected-link").symlink_to(external)
            else:
                os.mkfifo(workspace / "unexpected-fifo")
        write_new_json(
            output,
            SampleObservation(
                scenario=scenario,
                profile=profile,
                duration_ns=1,
                output_sha256="a" * 64,
                checkpoint_bytes=(
                    {"initialized_workspace": 1}
                    if scenario is ScenarioName.INITIALIZE
                    else {}
                ),
            ),
        )
        """
    )

    def launch(command: list[str | Path], **options: Any) -> subprocess.Popen[bytes]:
        if "--scenario" not in command:
            return cast(Any, original_popen(command, **options))
        scenario = str(command[command.index("--scenario") + 1])
        workspace = str(command[command.index("--workspace") + 1])
        output = str(command[command.index("--output") + 1])
        profile = str(command[command.index("--profile") + 1]) if "--profile" in command else "-"
        replacement = [
            sys.executable,
            "-c",
            script,
            scenario,
            workspace,
            profile,
            output,
            residue,
            str(external),
        ]
        return cast(Any, original_popen(replacement, **options))

    monkeypatch.setattr(runner_module.subprocess, "Popen", launch)


def test_timeout_terminates_then_kills_the_owned_worker_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_pid_file = tmp_path / "child.pid"
    term_marker = tmp_path / "term.marker"
    _replace_worker_with_hanging_process(
        monkeypatch,
        child_pid_file=child_pid_file,
        term_marker=term_marker,
    )

    def one_second_deadline(_scenario: ScenarioName) -> int:
        return 1

    monkeypatch.setattr(runner_module, "_deadline_seconds", one_second_deadline)
    output = tmp_path / "evidence.json"
    child_pid = 0

    try:
        with pytest.raises(BenchmarkRunError, match="deadline"):
            run_benchmarks(
                RunConfig(
                    profiles=(PROFILES["smoke"],),
                    output=output,
                    work_root=tmp_path / "work",
                    run_id="owned-timeout",
                    correctness_only=True,
                )
            )
        child_pid = int(child_pid_file.read_text(encoding="ascii"))

        assert term_marker.read_text(encoding="ascii") == "terminated"
        assert _wait_until_process_is_gone(child_pid)
        assert not output.exists()
    finally:
        if child_pid and _process_exists(child_pid):
            os.kill(child_pid, 9)


def _replace_worker_with_hanging_process(
    monkeypatch: pytest.MonkeyPatch,
    *,
    child_pid_file: Path,
    term_marker: Path,
) -> None:
    original_popen = subprocess.Popen
    script = textwrap.dedent(
        """
        import signal
        import subprocess
        import sys
        import time
        from pathlib import Path

        child_pid_file = Path(sys.argv[1])
        term_marker = Path(sys.argv[2])
        signal.signal(
            signal.SIGTERM,
            lambda _signum, _frame: term_marker.write_text("terminated", encoding="ascii"),
        )
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child_pid_file.write_text(str(child.pid), encoding="ascii")
        time.sleep(60)
        """
    )

    def launch(command: list[str | Path], **options: Any) -> subprocess.Popen[bytes]:
        if "--scenario" not in command:
            return cast(Any, original_popen(command, **options))
        replacement = [sys.executable, "-c", script, str(child_pid_file), str(term_marker)]
        return cast(Any, original_popen(replacement, **options))

    monkeypatch.setattr(runner_module.subprocess, "Popen", launch)


def _wait_until_process_is_gone(process_id: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _process_exists(process_id):
            return True
        time.sleep(0.05)
    return not _process_exists(process_id)


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("evidence_kind", ["missing", "symlink", "file"])
def test_report_invalid_evidence_directory_is_a_bounded_validation_failure(
    tmp_path: Path,
    evidence_kind: str,
) -> None:
    evidence = tmp_path / "invalid-evidence"
    if evidence_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        evidence.symlink_to(target, target_is_directory=True)
    elif evidence_kind == "file":
        evidence.write_text("not a directory", encoding="ascii")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks",
            "report",
            "--evidence",
            str(evidence),
            "--output",
            str(tmp_path / "report.md"),
            "--provisional",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Benchmark report failed: ValueError\n"
    assert str(tmp_path) not in result.stderr


def test_report_rejects_intermediate_symlink_alias_into_generated_fixture(
    tmp_path: Path,
) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    nested = fixture.workspace.root / "nested" / "deeper"
    nested.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(fixture.workspace.root / "nested", target_is_directory=True)
    evidence = tmp_path / "records"
    evidence.mkdir()
    write_evidence(evidence / "evidence.json", evidence_record())

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks",
            "report",
            "--evidence",
            str(evidence),
            "--output",
            str(alias / "deeper" / "evidence.json"),
            "--provisional",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert not (nested / "evidence.json").exists()
    assert str(tmp_path) not in result.stderr


def test_cli_rejects_work_root_beneath_intended_output_before_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "evidence.json"

    def unexpected_run(_config: RunConfig) -> None:
        raise AssertionError("path containment must fail before running")

    monkeypatch.setattr(benchmark_cli, "run_benchmarks", unexpected_run)

    with pytest.raises(SystemExit) as error:
        benchmark_cli.main(
            [
                "run",
                "--profiles",
                "smoke",
                "--correctness-only",
                "--output",
                str(output),
                "--work-root",
                str(output / "work"),
            ]
        )

    assert error.value.code == 2
    assert not output.exists()
