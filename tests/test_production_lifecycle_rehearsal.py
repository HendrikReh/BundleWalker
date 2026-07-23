# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts/rehearse_production_lifecycle.py"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_lifecycle_rehearsal", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _load_harness()


@pytest.mark.parametrize("value", ["0.4.0rc1", "0.4.0rc2", "0.4.0rc19"])
def test_release_candidate_validation_accepts_exact_values(value: str) -> None:
    assert HARNESS.validate_release_candidate(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "0.4.0",
        "0.4.0a2",
        "0.4.0rc0",
        "0.4.0rc01",
        "v0.4.0rc2",
        " 0.4.0rc2",
        "0.4.0rc2 ",
        "0.4.1rc1",
        "0.4.0rc2; echo unsafe",
    ],
)
def test_release_candidate_validation_rejects_every_other_shape(value: str) -> None:
    with pytest.raises(ValueError, match=r"exact 0.4.0 release candidate"):
        HARNESS.validate_release_candidate(value)


def test_sanitization_replaces_run_root_recursively_and_bounds_output(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    nested = {
        "path": str(root / "workspace"),
        "items": [f"before {root}/archive.zip after", {"plain": "safe"}],
    }

    assert HARNESS.sanitize_value(nested, root) == {
        "path": "$RUN_ROOT/workspace",
        "items": ["before $RUN_ROOT/archive.zip after", {"plain": "safe"}],
    }
    bounded = HARNESS.bounded_text("x" * 25_000 + str(root), root)
    assert len(bounded) <= HARNESS.MAX_CAPTURE_CHARACTERS + len(HARNESS.TRUNCATION_MARKER)
    assert str(root) not in bounded
    assert HARNESS.TRUNCATION_MARKER in bounded


def test_run_command_records_safe_success_and_failure(tmp_path: Path) -> None:
    success = HARNESS.run_command(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        run_root=tmp_path,
    )
    failure = HARNESS.run_command(
        [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
        cwd=tmp_path,
        run_root=tmp_path,
    )

    assert success["exit_code"] == 0
    assert success["stdout"] == "ok\n"
    assert failure["exit_code"] == 7
    assert failure["stderr"] == "bad\n"
    assert success["cwd"] == "$RUN_ROOT"
    assert isinstance(success["elapsed_seconds"], float)


def test_write_evidence_is_atomic_sanitized_and_newline_terminated(tmp_path: Path) -> None:
    root = tmp_path / "run"
    output = root / "evidence" / "evidence.json"

    HARNESS.write_evidence(
        output,
        {"result": "passed", "workspace": str(root / "original")},
        root,
    )

    assert not output.with_suffix(".json.tmp").exists()
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "result": "passed",
        "workspace": "$RUN_ROOT/original",
    }
