# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from bundlewalker.application import (
    DIAGNOSTIC_CHECK_CATALOG,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)
from bundlewalker.cli import app
from bundlewalker.interfaces.doctor import (
    SupportReportTargetError,
    SupportReportWriteError,
    render_diagnostic_lines,
    write_support_report,
)
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
runner = CliRunner()


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | str]]:
    snapshot: dict[str, tuple[str, int, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode, b"")
        else:
            snapshot[relative] = ("file", mode, path.read_bytes())
    return snapshot


def _result(
    overrides: Mapping[str, tuple[DiagnosticSeverity, tuple[str, ...]]],
) -> DiagnosticResult:
    checks = tuple(
        DiagnosticCheck(
            code=code,
            category=category,
            severity=overrides.get(code, (DiagnosticSeverity.PASS, ()))[0],
            summary=f"Safe summary for {code}.",
            remediation=overrides.get(code, (DiagnosticSeverity.PASS, ()))[1],
        )
        for code, category in DIAGNOSTIC_CHECK_CATALOG
    )
    counts = DiagnosticCounts(
        passed=sum(check.severity is DiagnosticSeverity.PASS for check in checks),
        warnings=sum(check.severity is DiagnosticSeverity.WARNING for check in checks),
        failures=sum(check.severity is DiagnosticSeverity.FAILURE for check in checks),
    )
    overall = (
        DiagnosticSeverity.FAILURE
        if counts.failures
        else DiagnosticSeverity.WARNING
        if counts.warnings
        else DiagnosticSeverity.PASS
    )
    return DiagnosticResult(
        overall=overall,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=counts,
        checks=checks,
    )


def test_renderer_uses_stable_tokens_order_remediation_and_summary() -> None:
    result = _result(
        {
            "configuration.model": (
                DiagnosticSeverity.WARNING,
                ("Set BUNDLEWALKER_MODEL before model-backed commands.",),
            ),
            "workspace.discovery": (
                DiagnosticSeverity.FAILURE,
                ("Run `bundlewalker init PATH` or pass an existing workspace.",),
            ),
        }
    )

    lines = render_diagnostic_lines(result)

    assert lines[0].startswith("PASS runtime.bundlewalker — ")
    assert any(line.startswith("WARN configuration.model — ") for line in lines)
    assert any(line.startswith("FAIL workspace.discovery — ") for line in lines)
    assert "  Next: Set BUNDLEWALKER_MODEL before model-backed commands." in lines
    assert lines[-1] == "Doctor: 12 passed, 1 warning, 1 failure."


def test_report_writer_creates_owner_only_json_and_refuses_existing_target(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "support.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    write_support_report(report, destination)

    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert SupportReport.model_validate_json(destination.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    original = destination.read_bytes()
    with pytest.raises(SupportReportTargetError):
        write_support_report(report, destination)
    assert destination.read_bytes() == original


def test_report_writer_refuses_symlink_directory_and_missing_parent(tmp_path: Path) -> None:
    report = SupportReport(generated_at=NOW, result=_result({}))
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(existing)

    for destination in (linked, tmp_path, tmp_path / "missing" / "report.json"):
        with pytest.raises(SupportReportTargetError):
            write_support_report(report, destination)
    assert existing.read_text(encoding="utf-8") == "keep"


def test_report_writer_treats_no_follow_rejection_as_an_unsafe_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "linked.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    def reject_link(
        _path: Path,
        _flags: int,
        _mode: int,
    ) -> int:
        raise OSError(errno.ELOOP, "private target failure")

    monkeypatch.setattr(os, "open", reject_link)

    with pytest.raises(SupportReportTargetError):
        write_support_report(report, destination)
    assert not destination.exists()


def test_report_writer_removes_only_its_partial_file_on_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "partial.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise FileNotFoundError("private write failure")

    monkeypatch.setattr(os, "write", fail_write)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert not destination.exists()


def test_doctor_runs_outside_workspace_and_returns_failure_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "FAIL workspace.discovery" in result.stdout
    assert "Doctor:" in result.stdout
    assert "Traceback" not in result.output
    assert not (tmp_path / ".bundlewalker").exists()


def test_doctor_warning_only_workspace_exits_zero_and_does_not_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    monkeypatch.delenv("BUNDLEWALKER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = _tree_snapshot(workspace.root)

    result = runner.invoke(app, ["doctor", str(workspace.root)])

    assert result.exit_code == 0
    assert "WARN configuration.model" in result.stdout
    assert "0 failures" in result.stdout
    assert _tree_snapshot(workspace.root) == before


def test_doctor_writes_only_explicit_report_and_never_echoes_private_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "private-workspace", occurred_at=NOW)
    report = tmp_path / "support.json"
    secret = "private-api-secret"
    model = "openai:private-model"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("BUNDLEWALKER_MODEL", model)
    before = _tree_snapshot(workspace.root)

    result = runner.invoke(
        app,
        ["doctor", str(workspace.root), "--report", str(report)],
    )

    assert result.exit_code == 0
    payload = report.read_text(encoding="utf-8")
    combined = result.output + payload
    assert SupportReport.model_validate_json(payload).schema_version == 1
    assert secret not in combined
    assert model not in combined
    assert str(workspace.root) not in combined
    assert str(report) not in combined
    assert _tree_snapshot(workspace.root) == before


def test_doctor_existing_report_target_is_a_usage_error(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    report = tmp_path / "existing.json"
    report.write_text("keep", encoding="utf-8")

    result = runner.invoke(
        app,
        ["doctor", str(workspace.root), "--report", str(report)],
    )

    assert result.exit_code == 2
    assert "Error: support report target must be a new file" in result.output
    assert str(report) not in result.output
    assert "Traceback" not in result.output
    assert report.read_text(encoding="utf-8") == "keep"


def test_doctor_report_write_failure_is_safe_and_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    report = tmp_path / "support.json"

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise OSError("private write failure")

    monkeypatch.setattr(os, "write", fail_write)

    result = runner.invoke(
        app,
        ["doctor", str(workspace.root), "--report", str(report)],
    )

    assert result.exit_code == 1
    assert "Error: support report could not be written" in result.output
    assert "private write failure" not in result.output
    assert str(report) not in result.output
    assert "Traceback" not in result.output
    assert not report.exists()


def test_doctor_help_shows_path_and_report_option() -> None:
    result = runner.invoke(app, ["doctor", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0, result.output
    assert "PATH" in output
    assert "--report" in output
    assert "REPORT.json" in output
