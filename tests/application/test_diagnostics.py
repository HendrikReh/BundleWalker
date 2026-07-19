# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import bundlewalker.application.diagnostics as diagnostics_module
from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    DiagnosticCheck,
    DiagnosticResult,
    DiagnosticsApplication,
    DiagnosticsDependencies,
    DiagnosticSeverity,
)
from bundlewalker.compatibility import CompatibilityStatus, WorkspaceCompatibility
from bundlewalker.transactions import TransactionDiagnosticStatus
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
ONE_GIB = 1024**3


def _dependencies() -> DiagnosticsDependencies:
    return DiagnosticsDependencies(
        environment={
            "BUNDLEWALKER_MODEL": "openai:private-model",
            "OPENAI_API_KEY": "secret",
        },
        bundlewalker_version="0.4.0a2",
        python_version=(3, 13, 5),
        platform_name="Linux",
        clock=lambda: NOW,
        module_available=lambda name: name == "mcp",
        executable_lookup=(
            lambda name: "/private/bin/bundlewalker-mcp" if name == "bundlewalker-mcp" else None
        ),
        permission_check=lambda _path, _mode: True,
        disk_free=lambda _path: 2 * ONE_GIB,
    )


def _by_code(result: DiagnosticResult) -> dict[str, DiagnosticCheck]:
    return {check.code: check for check in result.checks}


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


def test_diagnostics_run_returns_full_catalog_and_redacts_environment_values(
    tmp_path: Path,
) -> None:
    private_model = "openai:private-model"
    private_key = "secret-api-key"
    dependencies = replace(
        _dependencies(),
        environment={"BUNDLEWALKER_MODEL": private_model, "OPENAI_API_KEY": private_key},
    )

    result = DiagnosticsApplication(dependencies).run(tmp_path)
    serialized = result.model_dump_json()
    checks = _by_code(result)

    assert len(result.checks) == 14
    assert checks["runtime.python"].severity is DiagnosticSeverity.PASS
    assert checks["runtime.platform"].severity is DiagnosticSeverity.PASS
    assert checks["configuration.model"].severity is DiagnosticSeverity.PASS
    assert checks["configuration.credential"].severity is DiagnosticSeverity.PASS
    assert checks["mcp.package"].severity is DiagnosticSeverity.PASS
    assert checks["mcp.entrypoint"].severity is DiagnosticSeverity.PASS
    assert private_model not in serialized
    assert private_key not in serialized
    assert "/private" not in serialized


def test_diagnostics_warning_policy_for_optional_and_experimental_environment(
    tmp_path: Path,
) -> None:
    def low_disk(_path: Path) -> int:
        return ONE_GIB - 1

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            environment={},
            platform_name="Windows",
            disk_free=low_disk,
        )
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["runtime.platform"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.model"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.credential"].severity is DiagnosticSeverity.WARNING
    assert checks["storage.disk"].severity is DiagnosticSeverity.WARNING


def test_diagnostics_unsupported_python_and_missing_mcp_are_failures(
    tmp_path: Path,
) -> None:
    def module_missing(_name: str) -> bool:
        return False

    def executable_missing(_name: str) -> str | None:
        return None

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            python_version=(3, 12, 9),
            module_available=module_missing,
            executable_lookup=executable_missing,
        )
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["runtime.python"].severity is DiagnosticSeverity.FAILURE
    assert checks["mcp.package"].severity is DiagnosticSeverity.FAILURE
    assert checks["mcp.entrypoint"].severity is DiagnosticSeverity.FAILURE
    assert result.overall is DiagnosticSeverity.FAILURE


def test_diagnostics_unexpected_defect_uses_bounded_application_error(
    tmp_path: Path,
) -> None:
    marker = "private-programming-defect"

    def fail_lookup(_name: str) -> bool:
        raise RuntimeError(marker)

    with pytest.raises(ApplicationError) as raised:
        DiagnosticsApplication(replace(_dependencies(), module_available=fail_lookup)).run(tmp_path)

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert marker not in raised.value.safe_message


def test_diagnostics_current_workspace_passes_workspace_checks(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    result = DiagnosticsApplication(_dependencies()).run(workspace.root)
    checks = _by_code(result)

    for code in (
        "workspace.discovery",
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.PASS
    assert checks["workspace.permissions"].summary == (
        "Required workspace paths passed non-mutating access checks."
    )


@pytest.mark.parametrize("start_kind", ["workspace", "directory", "file"])
def test_diagnostics_preserves_workspace_start_semantics(
    tmp_path: Path,
    start_kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    child = workspace.root / "nested"
    child.mkdir()
    start_file = child / "note.txt"
    start_file.write_bytes(b"start file\n")
    starts = {
        "workspace": workspace.root,
        "directory": child,
        "file": start_file,
    }

    result = DiagnosticsApplication(_dependencies()).run(starts[start_kind])

    assert _by_code(result)["workspace.discovery"].severity is DiagnosticSeverity.PASS


@pytest.mark.parametrize("unsafe_kind", ["symlink", "directory"])
def test_diagnostics_nearest_unsafe_config_blocks_valid_ancestor_without_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "ancestor", occurred_at=NOW)
    child = workspace.root / "nested" / "child"
    child.mkdir(parents=True)
    unsafe_config = child / "bundlewalker.toml"
    if unsafe_kind == "symlink":
        unsafe_config.symlink_to(workspace.root / "bundlewalker.toml")
    else:
        unsafe_config.mkdir()

    calls = {"workspace": 0, "transaction": 0}
    discover_workspace = diagnostics_module.discover_workspace

    def count_workspace_discovery(start: Path | None = None) -> Workspace:
        calls["workspace"] += 1
        return discover_workspace(start)

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        calls["transaction"] += 1
        return TransactionDiagnosticStatus.CLEAN

    monkeypatch.setattr(
        diagnostics_module,
        "discover_workspace",
        count_workspace_discovery,
    )
    dependencies = replace(_dependencies(), transaction_inspector=count_transaction)

    result = DiagnosticsApplication(dependencies).run(child)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    for code in (
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.WARNING
    assert calls == {"workspace": 0, "transaction": 0}


def test_diagnostics_missing_workspace_fails_discovery_and_marks_dependents_skipped(
    tmp_path: Path,
) -> None:
    result = DiagnosticsApplication(_dependencies()).run(tmp_path)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    for code in (
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.WARNING


def test_diagnostics_invalid_current_configuration_is_bounded(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.root / "bundlewalker.toml").write_text("version = 1\n", encoding="utf-8")

    result = DiagnosticsApplication(_dependencies()).run(workspace.root)
    serialized = result.model_dump_json()

    assert _by_code(result)["workspace.configuration"].severity is DiagnosticSeverity.FAILURE
    assert str(workspace.root) not in serialized
    assert "Traceback" not in serialized


def test_diagnostics_future_workspace_reports_compatibility_without_current_parse(
    tmp_path: Path,
) -> None:
    root = tmp_path / "future"
    root.mkdir()
    (root / "bundlewalker.toml").write_text(
        "version = 2\nfuture_path = 'private'\n",
        encoding="utf-8",
    )

    result = DiagnosticsApplication(_dependencies()).run(root)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.WARNING
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.FAILURE


@pytest.mark.parametrize(
    ("status", "summary", "remediation_command"),
    [
        (
            CompatibilityStatus.UPGRADEABLE,
            "The workspace format requires an explicit upgrade.",
            "bundlewalker workspace upgrade PATH",
        ),
        (
            CompatibilityStatus.UNSUPPORTED,
            "The workspace format is unsupported.",
            "bundlewalker workspace status PATH",
        ),
    ],
)
def test_diagnostics_noncurrent_compatibility_is_bounded_and_gates_current_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: CompatibilityStatus,
    summary: str,
    remediation_command: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    calls = {"workspace": 0, "transaction": 0}

    def inspect_as_noncurrent(_start: Path | None = None) -> WorkspaceCompatibility:
        return WorkspaceCompatibility(
            root=workspace.root,
            config_path=workspace.root / "bundlewalker.toml",
            workspace_format_version=0,
            status=status,
            readable=False,
            writable=False,
            upgrade_available=status is CompatibilityStatus.UPGRADEABLE,
        )

    def count_workspace_discovery(_start: Path | None = None) -> Workspace:
        calls["workspace"] += 1
        return workspace

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        calls["transaction"] += 1
        return TransactionDiagnosticStatus.CLEAN

    monkeypatch.setattr(diagnostics_module, "inspect_workspace", inspect_as_noncurrent)
    monkeypatch.setattr(
        diagnostics_module,
        "discover_workspace",
        count_workspace_discovery,
    )
    dependencies = replace(_dependencies(), transaction_inspector=count_transaction)

    result = DiagnosticsApplication(dependencies).run(workspace.root)
    checks = _by_code(result)

    assert checks["workspace.configuration"].severity is DiagnosticSeverity.WARNING
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.compatibility"].summary == summary
    assert remediation_command in " ".join(checks["workspace.compatibility"].remediation)
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert calls == {"workspace": 0, "transaction": 0}


def test_diagnostics_broken_structure_gates_permissions_and_transactions(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    workspace.raw_dir.rmdir()
    workspace.raw_dir.write_bytes(b"wrong node kind\n")
    before = _tree_snapshot(workspace.root)
    transaction_calls = 0

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    dependencies = replace(_dependencies(), transaction_inspector=count_transaction)

    result = DiagnosticsApplication(dependencies).run(workspace.root)
    checks = _by_code(result)

    assert checks["workspace.structure"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.permissions"].severity is DiagnosticSeverity.WARNING
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0
    assert _tree_snapshot(workspace.root) == before


def test_diagnostics_write_permission_denial_is_failure_without_probe_file(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = sorted(path.relative_to(workspace.root) for path in workspace.root.rglob("*"))

    def deny_write(_path: Path, mode: int) -> bool:
        return mode != os.W_OK

    dependencies = replace(_dependencies(), permission_check=deny_write)

    result = DiagnosticsApplication(dependencies).run(workspace.root)

    assert _by_code(result)["workspace.permissions"].severity is DiagnosticSeverity.FAILURE
    assert sorted(path.relative_to(workspace.root) for path in workspace.root.rglob("*")) == before


def test_diagnostics_run_preserves_bytes_modes_node_kinds_and_symlink_targets(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    marker = workspace.root / "diagnostic-link"
    marker.symlink_to("raw")
    os.chmod(workspace.conventions_file, 0o640)
    before = _tree_snapshot(workspace.root)

    DiagnosticsApplication(_dependencies()).run(workspace.root)

    link_kind, _link_mode, link_target = before["diagnostic-link"]
    assert (link_kind, link_target) == ("symlink", "raw")
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    ("state", "severity"),
    [
        (TransactionDiagnosticStatus.CLEAN, DiagnosticSeverity.PASS),
        (TransactionDiagnosticStatus.PENDING, DiagnosticSeverity.WARNING),
        (TransactionDiagnosticStatus.BUSY, DiagnosticSeverity.WARNING),
        (TransactionDiagnosticStatus.INTERRUPTED, DiagnosticSeverity.FAILURE),
        (TransactionDiagnosticStatus.MALFORMED, DiagnosticSeverity.FAILURE),
    ],
)
def test_diagnostics_maps_transaction_state_without_identifiers(
    tmp_path: Path,
    state: TransactionDiagnosticStatus,
    severity: DiagnosticSeverity,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def inspect_as(_workspace: object) -> TransactionDiagnosticStatus:
        return state

    result = DiagnosticsApplication(replace(_dependencies(), transaction_inspector=inspect_as)).run(
        workspace.root
    )

    check = _by_code(result)["transactions.state"]
    assert check.severity is severity
    assert (
        "<REVIEW_ID>" in " ".join(check.remediation)
        if state is TransactionDiagnosticStatus.PENDING
        else True
    )


@pytest.mark.parametrize("invalid_state", ["malformed", object()])
def test_diagnostics_invalid_transaction_inspector_return_is_bounded_defect(
    tmp_path: Path,
    invalid_state: object,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def inspect_invalid(_workspace: Workspace) -> TransactionDiagnosticStatus:
        return cast(TransactionDiagnosticStatus, invalid_state)

    with pytest.raises(ApplicationError) as raised:
        DiagnosticsApplication(replace(_dependencies(), transaction_inspector=inspect_invalid)).run(
            workspace.root
        )

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert isinstance(raised.value.__cause__, TypeError)


def test_diagnostics_support_report_uses_injected_timestamp_and_schema(
    tmp_path: Path,
) -> None:
    application = DiagnosticsApplication(_dependencies())
    result = application.run(tmp_path)

    report = application.support_report(result)

    assert report.schema_version == 1
    assert report.generated_at == NOW
    assert report.result is result
    assert set(report.model_dump()) == {"schema_version", "generated_at", "result"}


def test_diagnostics_redacts_expected_inspector_failures(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "private-workspace", occurred_at=NOW)
    markers = {
        "private-model-marker",
        "private-key-marker",
        "private-executable-marker",
        "private-permission-marker",
        "private-disk-marker",
        "private-transaction-marker",
        "private-host-marker",
    }

    def fail_transaction(_workspace: object) -> TransactionDiagnosticStatus:
        raise OSError("private-transaction-marker")

    def fail_permission(_path: Path, _mode: int) -> bool:
        raise OSError("private-permission-marker")

    def fail_disk(_path: Path) -> int:
        raise OSError("private-disk-marker")

    def find_private_executable(_name: str) -> str | None:
        return "/private-executable-marker/bin"

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            environment={
                "BUNDLEWALKER_MODEL": "openai:private-model-marker",
                "OPENAI_API_KEY": "private-key-marker",
            },
            platform_name="private-host-marker",
            executable_lookup=find_private_executable,
            permission_check=fail_permission,
            disk_free=fail_disk,
            transaction_inspector=fail_transaction,
        )
    ).run(workspace.root)
    serialized = result.model_dump_json()

    assert _by_code(result)["transactions.state"].severity is DiagnosticSeverity.FAILURE
    assert all(marker not in serialized for marker in markers)
    assert str(workspace.root) not in serialized
