# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import sys
from pathlib import Path

from benchmarks.contracts import ScenarioDisposition
from benchmarks.evidence import load_evidence
from benchmarks.profiles import PROFILES
from benchmarks.runner import RunConfig, run_benchmarks

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
