# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import errno
import os
import stat
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from click import unstyle
from typer.testing import CliRunner

import bundlewalker.interfaces.cli as cli_module
from bundlewalker.application import (
    DIAGNOSTIC_CHECK_CATALOG,
    ApplicationError,
    ApplicationErrorCode,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticsApplication,
    DiagnosticsDependencies,
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

    assert lines[:3] == (
        "BundleWalker: 0.4.0a2",
        "Python: 3.13.5",
        "Platform: linux",
    )
    assert lines[3].startswith("PASS runtime.bundlewalker — ")
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


def test_report_writer_completes_short_writes_with_exact_content_and_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "short-writes.json"
    report = SupportReport(generated_at=NOW, result=_result({}))
    expected = (report.model_dump_json(indent=2) + "\n").encode()
    original_write = os.write
    write_calls = 0

    def write_short(descriptor: int, content: bytes | memoryview) -> int:
        nonlocal write_calls
        write_calls += 1
        return original_write(descriptor, content[:17])

    monkeypatch.setattr(os, "write", write_short)

    write_support_report(report, destination)

    assert write_calls > 1
    assert destination.read_bytes() == expected
    assert destination.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_report_writer_refuses_existing_fifo_without_blocking(tmp_path: Path) -> None:
    destination = tmp_path / "report.fifo"
    report = SupportReport(generated_at=NOW, result=_result({}))
    os.mkfifo(destination, 0o600)
    outcome: list[type[BaseException] | None] = []

    def write_fifo() -> None:
        try:
            write_support_report(report, destination)
        except BaseException as error:
            outcome.append(type(error))
        else:
            outcome.append(None)

    writer = threading.Thread(target=write_fifo, daemon=True)
    writer.start()
    writer.join(timeout=1)
    blocked = writer.is_alive()
    if blocked:
        reader = os.open(destination, os.O_RDONLY | os.O_NONBLOCK)
        writer.join(timeout=1)
        os.close(reader)

    assert not blocked
    assert outcome == [SupportReportTargetError]
    assert stat.S_ISFIFO(destination.stat().st_mode)


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


def test_report_writer_leaves_its_partial_file_on_write_failure(
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
    assert destination.read_bytes() == b""


def test_report_writer_treats_zero_write_as_failure_and_leaves_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "zero-write.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    def write_nothing(_descriptor: int, _content: bytes | memoryview) -> int:
        return 0

    monkeypatch.setattr(os, "write", write_nothing)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert destination.read_bytes() == b""


@pytest.mark.parametrize("operation", ["fchmod", "fsync"])
def test_report_writer_leaves_partial_on_descriptor_operation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    destination = tmp_path / f"{operation}-failure.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    def fail_operation(*_arguments: object) -> None:
        raise OSError(f"private {operation} failure")

    monkeypatch.setattr(os, operation, fail_operation)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert destination.exists()


def test_report_writer_never_deletes_replacement_installed_during_failure_handling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "replacement.json"
    report = SupportReport(generated_at=NOW, result=_result({}))
    replacement = b"unrelated replacement\n"
    original_lstat = Path.lstat
    original_unlink = Path.unlink
    original_close = os.close
    replacement_installed = False

    def install_replacement() -> None:
        nonlocal replacement_installed
        original_unlink(destination)
        destination.write_bytes(replacement)
        replacement_installed = True

    def replace_after_metadata_read(path: Path) -> os.stat_result:
        metadata = original_lstat(path)
        install_replacement()
        return metadata

    def replace_before_close(descriptor: int) -> None:
        if not replacement_installed:
            install_replacement()
        original_close(descriptor)

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise OSError("private write failure")

    monkeypatch.setattr(Path, "lstat", replace_after_metadata_read)
    monkeypatch.setattr(os, "close", replace_before_close)
    monkeypatch.setattr(os, "write", fail_write)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert replacement_installed
    assert destination.read_bytes() == replacement


def test_report_writer_treats_ambiguous_close_failure_as_write_failure_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "close-failure.json"
    report = SupportReport(generated_at=NOW, result=_result({}))
    original_close = os.close
    close_calls = 0

    def close_then_fail(descriptor: int) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(descriptor)
        raise OSError("private close failure")

    monkeypatch.setattr(os, "close", close_then_fail)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert close_calls == 1
    assert destination.exists()


def test_report_writer_closes_once_and_preserves_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "interrupted.json"
    report = SupportReport(generated_at=NOW, result=_result({}))
    interruption = KeyboardInterrupt("private interruption")
    original_close = os.close
    close_calls = 0

    def interrupt_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise interruption

    def close_then_fail(descriptor: int) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(descriptor)
        raise OSError("private close failure")

    monkeypatch.setattr(os, "write", interrupt_write)
    monkeypatch.setattr(os, "close", close_then_fail)

    with pytest.raises(KeyboardInterrupt) as raised:
        write_support_report(report, destination)

    assert raised.value is interruption
    assert close_calls == 1
    assert destination.exists()


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


def test_doctor_bounds_chained_application_failure_without_private_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = tmp_path / "private-diagnostic-source"

    def fail_lookup(_name: str) -> bool:
        try:
            raise OSError(f"could not inspect {private_path}")
        except OSError as cause:
            raise ApplicationError(
                ApplicationErrorCode.DIAGNOSTIC_FAILED,
                "diagnostic operation failed",
            ) from cause

    application = DiagnosticsApplication(DiagnosticsDependencies(module_available=fail_lookup))
    monkeypatch.setattr(cli_module, "DiagnosticsApplication", lambda: application)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert result.output == "Error: diagnostic operation failed\n"
    assert str(private_path) not in result.output
    assert "could not inspect" not in result.output
    assert "Traceback" not in result.output


def test_doctor_bounds_support_report_construction_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "support.json"
    private_marker = "private-clock-marker"

    def fail_clock() -> datetime:
        raise RuntimeError(private_marker)

    application = DiagnosticsApplication(DiagnosticsDependencies(clock=fail_clock))
    monkeypatch.setattr(cli_module, "DiagnosticsApplication", lambda: application)

    result = runner.invoke(app, ["doctor", "--report", str(report)])

    assert result.exit_code == 1
    assert "Error: diagnostic operation failed" in result.output
    assert private_marker not in result.output
    assert "Support report written." not in result.output
    assert str(report) not in result.output
    assert "Traceback" not in result.output
    assert not report.exists()


def test_doctor_bounds_private_support_report_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "support.json"
    private_marker = "private-validation-marker"

    def invalid_clock() -> datetime:
        return cast(datetime, private_marker)

    application = DiagnosticsApplication(DiagnosticsDependencies(clock=invalid_clock))
    monkeypatch.setattr(cli_module, "DiagnosticsApplication", lambda: application)

    result = runner.invoke(app, ["doctor", "--report", str(report)])

    assert result.exit_code == 1
    assert "Error: diagnostic operation failed" in result.output
    assert private_marker not in result.output
    assert "Input should be a valid datetime" not in result.output
    assert "Support report written." not in result.output
    assert str(report) not in result.output
    assert "Traceback" not in result.output
    assert not report.exists()


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


@pytest.mark.parametrize("start_kind", ["linked_directory", "explicit_config"])
def test_doctor_linked_parent_directory_and_explicit_config_select_the_same_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    linked_parent = tmp_path / "outside" / "workspace-link"
    linked_parent.parent.mkdir()
    linked_parent.symlink_to(workspace.root, target_is_directory=True)
    start = (
        linked_parent if start_kind == "linked_directory" else linked_parent / "bundlewalker.toml"
    )
    monkeypatch.delenv("BUNDLEWALKER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, ["doctor", str(start)])

    assert result.exit_code == 0
    for code in (
        "workspace.discovery",
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert f"PASS {code}" in result.stdout


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
    assert "Support report written." not in result.output
    assert report.read_bytes() == b""


def test_doctor_report_close_failure_is_safe_and_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    report = tmp_path / "support.json"
    original_close = os.close
    close_failed = False

    def fail_report_close(descriptor: int) -> None:
        nonlocal close_failed
        descriptor_metadata = os.fstat(descriptor)
        is_report = False
        if report.exists():
            report_metadata = report.stat()
            is_report = (descriptor_metadata.st_dev, descriptor_metadata.st_ino) == (
                report_metadata.st_dev,
                report_metadata.st_ino,
            )
        original_close(descriptor)
        if is_report and not close_failed:
            close_failed = True
            raise OSError("private close failure")

    monkeypatch.setattr(os, "close", fail_report_close)

    result = runner.invoke(
        app,
        ["doctor", str(workspace.root), "--report", str(report)],
    )

    assert result.exit_code == 1
    assert "Error: support report could not be written" in result.output
    assert "Support report written." not in result.output
    assert "private close failure" not in result.output
    assert str(report) not in result.output
    assert "Traceback" not in result.output
    assert report.exists()


def test_doctor_help_shows_path_and_report_option() -> None:
    result = runner.invoke(app, ["doctor", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0, result.output
    assert "PATH" in output
    assert "--report" in output
    assert "REPORT.json" in output
