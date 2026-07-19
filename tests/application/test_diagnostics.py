# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import SupportsIndex, cast

import pytest
from pydantic import ValidationError

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    DiagnosticCheck,
    DiagnosticResult,
    DiagnosticsApplication,
    DiagnosticsDependencies,
    DiagnosticSeverity,
)
from bundlewalker.compatibility import CompatibilityStatus, MigrationStep
from bundlewalker.transactions import QuiescentWorkspace, TransactionDiagnosticStatus
from bundlewalker.workspace import MAX_WORKSPACE_CONFIG_BYTES, Workspace, initialize_workspace

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
        distribution_available=lambda name: name == "mcp",
        console_script_targets=(
            lambda name: ("bundlewalker.interfaces.mcp:main",) if name == "bundlewalker-mcp" else ()
        ),
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


@pytest.mark.parametrize(
    ("environment", "model_severity", "credential_summary"),
    [
        (
            {"BUNDLEWALKER_MODEL": " \t\n "},
            DiagnosticSeverity.WARNING,
            "Provider credentials were not checked because no model is configured.",
        ),
        (
            {"BUNDLEWALKER_MODEL": "unknown:private-model"},
            DiagnosticSeverity.PASS,
            "Credential verification is unavailable for the configured provider.",
        ),
        (
            {"BUNDLEWALKER_MODEL": "openai:private-model"},
            DiagnosticSeverity.PASS,
            "The OpenAI credential is not configured.",
        ),
        (
            {"BUNDLEWALKER_MODEL": f"{' ' * 64}openai:private-model"},
            DiagnosticSeverity.PASS,
            "The OpenAI credential is not configured.",
        ),
    ],
)
def test_diagnostics_model_and_credential_policy_is_bounded_and_normalized(
    tmp_path: Path,
    environment: dict[str, str],
    model_severity: DiagnosticSeverity,
    credential_summary: str,
) -> None:
    result = DiagnosticsApplication(replace(_dependencies(), environment=environment)).run(tmp_path)
    checks = _by_code(result)

    assert checks["configuration.model"].severity is model_severity
    assert checks["configuration.credential"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.credential"].summary == credential_summary
    assert all(value not in result.model_dump_json() for value in environment.values())


def test_diagnostics_does_not_scan_unbounded_model_leading_whitespace(
    tmp_path: Path,
) -> None:
    class GuardedModel(str):
        def __iter__(self) -> Iterator[str]:
            raise AssertionError("model diagnostics iterated the complete provider value")

        def __getitem__(
            self,
            key: SupportsIndex
            | slice[SupportsIndex | None, SupportsIndex | None, SupportsIndex | None],
        ) -> str:
            assert isinstance(key, slice)
            assert key.start is None
            assert key.stop == 128
            assert key.step is None
            return super().__getitem__(key)

    model = GuardedModel(" " * 10_000 + "openai:private-model")

    result = DiagnosticsApplication(
        replace(_dependencies(), environment={"BUNDLEWALKER_MODEL": model})
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["configuration.model"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.model"].summary == "No agent model is configured."
    assert checks["configuration.credential"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.credential"].summary == (
        "Provider credentials were not checked because no model is configured."
    )


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


@pytest.mark.parametrize(
    "private_identity",
    ["private-version-marker\n0.4.0", "private-version-marker" * 20],
)
def test_diagnostics_bounds_invalid_bundlewalker_identity(
    tmp_path: Path,
    private_identity: str,
) -> None:
    result = DiagnosticsApplication(
        replace(_dependencies(), bundlewalker_version=private_identity)
    ).run(tmp_path)

    assert result.bundlewalker_version == "unknown"
    assert _by_code(result)["runtime.bundlewalker"].severity is DiagnosticSeverity.FAILURE
    assert "private-version-marker" not in result.model_dump_json()


def test_diagnostics_reports_missing_bundlewalker_identity_without_aborting(
    tmp_path: Path,
) -> None:
    result = DiagnosticsApplication(replace(_dependencies(), bundlewalker_version="")).run(tmp_path)

    assert len(result.checks) == 14
    assert result.bundlewalker_version == "unknown"
    assert _by_code(result)["runtime.bundlewalker"].severity is DiagnosticSeverity.FAILURE


@pytest.mark.parametrize(
    ("python_version", "severity"),
    [
        ((3, 13, 0), DiagnosticSeverity.PASS),
        ((3, 14, 9), DiagnosticSeverity.PASS),
        ((3, 12, 9), DiagnosticSeverity.FAILURE),
        ((3, 15, 0), DiagnosticSeverity.FAILURE),
    ],
)
def test_diagnostics_python_support_policy(
    tmp_path: Path,
    python_version: tuple[int, int, int],
    severity: DiagnosticSeverity,
) -> None:
    result = DiagnosticsApplication(replace(_dependencies(), python_version=python_version)).run(
        tmp_path
    )

    assert _by_code(result)["runtime.python"].severity is severity


@pytest.mark.parametrize(
    ("platform_name", "normalized_name", "severity"),
    [
        ("Darwin", "macos", DiagnosticSeverity.PASS),
        ("Linux", "linux", DiagnosticSeverity.PASS),
        ("Windows", "windows", DiagnosticSeverity.WARNING),
        ("FreeBSD", "other", DiagnosticSeverity.WARNING),
    ],
)
def test_diagnostics_platform_support_policy(
    tmp_path: Path,
    platform_name: str,
    normalized_name: str,
    severity: DiagnosticSeverity,
) -> None:
    result = DiagnosticsApplication(replace(_dependencies(), platform_name=platform_name)).run(
        tmp_path
    )

    assert result.platform == normalized_name
    assert _by_code(result)["runtime.platform"].severity is severity


@pytest.mark.parametrize(
    ("package_available", "entrypoint_available"),
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_diagnostics_mcp_package_and_entrypoint_are_independent(
    tmp_path: Path,
    package_available: bool,
    entrypoint_available: bool,
) -> None:
    def module_available(_name: str) -> bool:
        return package_available

    def executable_lookup(_name: str) -> str | None:
        return "/private/bin/bundlewalker-mcp" if entrypoint_available else None

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            module_available=module_available,
            executable_lookup=executable_lookup,
        )
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["mcp.package"].severity is (
        DiagnosticSeverity.PASS if package_available else DiagnosticSeverity.FAILURE
    )
    assert checks["mcp.entrypoint"].severity is (
        DiagnosticSeverity.PASS if entrypoint_available else DiagnosticSeverity.FAILURE
    )
    assert "/private" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("metadata_available", "module_available", "severity"),
    [
        (True, True, DiagnosticSeverity.PASS),
        (True, False, DiagnosticSeverity.FAILURE),
        (False, True, DiagnosticSeverity.FAILURE),
        (False, False, DiagnosticSeverity.FAILURE),
    ],
)
def test_diagnostics_mcp_package_requires_metadata_and_module_availability(
    tmp_path: Path,
    metadata_available: bool,
    module_available: bool,
    severity: DiagnosticSeverity,
) -> None:
    def distribution_available(_name: str) -> bool:
        return metadata_available

    def find_module(_name: str) -> bool:
        return module_available

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            distribution_available=distribution_available,
            module_available=find_module,
        )
    ).run(tmp_path)

    assert _by_code(result)["mcp.package"].severity is severity


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_diagnostics_contains_mcp_distribution_metadata_os_failures(
    tmp_path: Path,
    error_type: type[OSError],
) -> None:
    marker = "private-mcp-distribution-marker"

    def fail_distribution(_name: str) -> bool:
        raise error_type(marker)

    result = DiagnosticsApplication(
        replace(_dependencies(), distribution_available=fail_distribution)
    ).run(tmp_path)

    assert len(result.checks) == 14
    assert _by_code(result)["mcp.package"].severity is DiagnosticSeverity.FAILURE
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_diagnostics_contains_mcp_module_availability_os_failures(
    tmp_path: Path,
    error_type: type[OSError],
) -> None:
    marker = "private-mcp-module-marker"

    def fail_module(_name: str) -> bool:
        raise error_type(marker)

    result = DiagnosticsApplication(replace(_dependencies(), module_available=fail_module)).run(
        tmp_path
    )

    assert len(result.checks) == 14
    assert _by_code(result)["mcp.package"].severity is DiagnosticSeverity.FAILURE
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize(
    ("targets", "executable", "severity"),
    [
        (
            ("bundlewalker.interfaces.mcp:main",),
            "/private/bin/bundlewalker-mcp",
            DiagnosticSeverity.PASS,
        ),
        (("bundlewalker.interfaces.mcp:main",), None, DiagnosticSeverity.FAILURE),
        (("private.module:main",), "/private/bin/bundlewalker-mcp", DiagnosticSeverity.FAILURE),
        ((), "/private/bin/bundlewalker-mcp", DiagnosticSeverity.FAILURE),
    ],
)
def test_diagnostics_mcp_entrypoint_requires_expected_metadata_and_executable(
    tmp_path: Path,
    targets: tuple[str, ...],
    executable: str | None,
    severity: DiagnosticSeverity,
) -> None:
    def console_script_targets(_name: str) -> tuple[str, ...]:
        return targets

    def executable_lookup(_name: str) -> str | None:
        return executable

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            console_script_targets=console_script_targets,
            executable_lookup=executable_lookup,
        )
    ).run(tmp_path)

    assert _by_code(result)["mcp.entrypoint"].severity is severity


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_diagnostics_contains_mcp_entrypoint_metadata_os_failures(
    tmp_path: Path,
    error_type: type[OSError],
) -> None:
    marker = "private-mcp-entrypoint-metadata-marker"

    def fail_targets(_name: str) -> tuple[str, ...]:
        raise error_type(marker)

    result = DiagnosticsApplication(
        replace(_dependencies(), console_script_targets=fail_targets)
    ).run(tmp_path)

    assert len(result.checks) == 14
    assert _by_code(result)["mcp.entrypoint"].severity is DiagnosticSeverity.FAILURE
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_diagnostics_contains_mcp_executable_lookup_os_failures(
    tmp_path: Path,
    error_type: type[OSError],
) -> None:
    marker = "private-mcp-executable-marker"

    def fail_executable(_name: str) -> str | None:
        raise error_type(marker)

    result = DiagnosticsApplication(
        replace(_dependencies(), executable_lookup=fail_executable)
    ).run(tmp_path)

    assert len(result.checks) == 14
    assert _by_code(result)["mcp.entrypoint"].severity is DiagnosticSeverity.FAILURE
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize(
    "dependency",
    [
        "distribution_available",
        "module_available",
        "console_script_targets",
        "executable_lookup",
    ],
)
def test_diagnostics_does_not_hide_unexpected_mcp_programming_defects(
    tmp_path: Path,
    dependency: str,
) -> None:
    marker = "private-mcp-programming-defect"

    def fail(_name: str) -> object:
        raise RuntimeError(marker)

    dependencies = replace(_dependencies(), **{dependency: fail})

    with pytest.raises(ApplicationError) as raised:
        DiagnosticsApplication(dependencies).run(tmp_path)

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert raised.value.__cause__ is not None
    assert marker not in raised.value.safe_message


def test_diagnostics_disk_inspection_unavailability_is_a_bounded_warning(
    tmp_path: Path,
) -> None:
    marker = "private-disk-inspection-marker"

    def fail_disk(_path: Path) -> int:
        raise OSError(marker)

    result = DiagnosticsApplication(replace(_dependencies(), disk_free=fail_disk)).run(tmp_path)
    check = _by_code(result)["storage.disk"]

    assert check.severity is DiagnosticSeverity.WARNING
    assert check.summary == "Available disk space could not be inspected."
    assert marker not in result.model_dump_json()


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


@pytest.mark.parametrize(
    "start_kind",
    ["workspace_directory", "workspace_config", "ancestor_directory", "ancestor_file"],
)
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
        "workspace_directory": workspace.root,
        "workspace_config": workspace.root / "bundlewalker.toml",
        "ancestor_directory": child,
        "ancestor_file": start_file,
    }

    result = DiagnosticsApplication(_dependencies()).run(starts[start_kind])

    assert _by_code(result)["workspace.discovery"].severity is DiagnosticSeverity.PASS


def test_diagnostics_none_start_discovers_from_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    child = workspace.root / "nested"
    child.mkdir()
    monkeypatch.chdir(child)

    result = DiagnosticsApplication(_dependencies()).run()

    assert _by_code(result)["workspace.discovery"].severity is DiagnosticSeverity.PASS


def test_diagnostics_symlink_to_ordinary_child_file_uses_target_parent(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    child = workspace.root / "nested"
    child.mkdir()
    target = child / "note.txt"
    target.write_bytes(b"ordinary child file\n")
    start = tmp_path / "outside" / "start-link"
    start.parent.mkdir()
    start.symlink_to(target)

    result = DiagnosticsApplication(_dependencies()).run(start)
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


def test_diagnostics_symlink_to_workspace_directory_uses_target_workspace(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    start = tmp_path / "outside" / "workspace-link"
    start.parent.mkdir()
    start.symlink_to(workspace.root, target_is_directory=True)

    result = DiagnosticsApplication(_dependencies()).run(start)
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


@pytest.mark.parametrize("unsafe_kind", ["symlink", "directory", "fifo"])
def test_diagnostics_nearest_unsafe_config_blocks_valid_ancestor_without_inspection(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "ancestor", occurred_at=NOW)
    child = workspace.root / "nested" / "child"
    child.mkdir(parents=True)
    unsafe_config = child / "bundlewalker.toml"
    if unsafe_kind == "symlink":
        unsafe_config.symlink_to(workspace.root / "bundlewalker.toml")
    elif unsafe_kind == "directory":
        unsafe_config.mkdir()
    else:
        os.mkfifo(unsafe_config)

    transaction_calls = 0

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    dependencies = replace(_dependencies(), transaction_inspector=count_transaction)

    result = DiagnosticsApplication(dependencies).run(child)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.discovery"].summary == (
        "An unsafe BundleWalker workspace configuration was found."
    )
    assert checks["workspace.discovery"].remediation == (
        "Replace bundlewalker.toml with a regular non-linked configuration file.",
    )
    for code in (
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


@pytest.mark.parametrize("unsafe_kind", ["symlink", "directory", "fifo"])
def test_diagnostics_explicit_unsafe_config_start_never_falls_through(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "ancestor", occurred_at=NOW)
    child = workspace.root / "nested"
    child.mkdir()
    unsafe_config = child / "bundlewalker.toml"
    if unsafe_kind == "symlink":
        unsafe_config.symlink_to(workspace.root / "bundlewalker.toml")
    elif unsafe_kind == "directory":
        unsafe_config.mkdir()
    else:
        os.mkfifo(unsafe_config)
    transaction_calls = 0

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    result = DiagnosticsApplication(
        replace(_dependencies(), transaction_inspector=count_transaction)
    ).run(unsafe_config)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.discovery"].summary == (
        "An unsafe BundleWalker workspace configuration was found."
    )
    assert checks["workspace.discovery"].remediation == (
        "Replace bundlewalker.toml with a regular non-linked configuration file.",
    )
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


def test_diagnostics_explicit_missing_config_start_never_falls_through(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "ancestor", occurred_at=NOW)
    child = workspace.root / "nested"
    child.mkdir()
    missing_config = child / "bundlewalker.toml"
    transaction_calls = 0

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    result = DiagnosticsApplication(
        replace(_dependencies(), transaction_inspector=count_transaction)
    ).run(missing_config)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.discovery"].summary == "No usable BundleWalker workspace was found."
    assert checks["workspace.discovery"].remediation == (
        "Run `bundlewalker init PATH` or pass an existing workspace to `bundlewalker doctor PATH`.",
    )
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


def test_diagnostics_reads_one_opened_config_snapshot_during_final_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    config_path = workspace.root / "bundlewalker.toml"
    retained_config = workspace.root / "retained-config.toml"
    outside_config = tmp_path / "outside.toml"
    outside_config.write_bytes(b"version = " + b"9" * 5_000 + b"\n")
    transaction_calls = 0
    config_descriptor: int | None = None
    config_opens = 0
    swapped = False
    original_open = os.open
    original_fstat = os.fstat

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal config_descriptor, config_opens
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == "bundlewalker.toml" and dir_fd is not None:
            config_descriptor = descriptor
            config_opens += 1
            assert flags & getattr(os, "O_NOFOLLOW", 0)
            assert flags & getattr(os, "O_NONBLOCK", 0)
        return descriptor

    def swap_after_fstat(descriptor: int) -> os.stat_result:
        nonlocal swapped
        metadata = original_fstat(descriptor)
        if descriptor == config_descriptor and not swapped:
            config_path.rename(retained_config)
            config_path.symlink_to(outside_config)
            swapped = True
        return metadata

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "fstat", swap_after_fstat)
        result = DiagnosticsApplication(
            replace(_dependencies(), transaction_inspector=count_transaction)
        ).run(workspace.root)

    checks = _by_code(result)
    assert swapped
    assert config_opens == 1
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.structure"].severity is DiagnosticSeverity.FAILURE
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


def test_diagnostics_stays_on_opened_root_during_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    selected_root = workspace.root
    retained_root = tmp_path / "retained-root"
    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    (outside_root / "bundlewalker.toml").write_bytes(b"version = " + b"9" * 5_000 + b"\n")
    transaction_calls = 0
    replaced = False
    original_open = os.open

    def replace_before_config_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        if os.fsdecode(path) == "bundlewalker.toml" and dir_fd is not None and not replaced:
            selected_root.rename(retained_root)
            selected_root.symlink_to(outside_root, target_is_directory=True)
            replaced = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", replace_before_config_open)
        result = DiagnosticsApplication(
            replace(_dependencies(), transaction_inspector=count_transaction)
        ).run(selected_root)

    checks = _by_code(result)
    assert replaced
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.structure"].severity is DiagnosticSeverity.FAILURE
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


def test_diagnostics_missing_workspace_fails_discovery_and_marks_dependents_skipped(
    tmp_path: Path,
) -> None:
    result = DiagnosticsApplication(_dependencies()).run(tmp_path)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.discovery"].summary == "No usable BundleWalker workspace was found."
    assert checks["workspace.discovery"].remediation == (
        "Run `bundlewalker init PATH` or pass an existing workspace to `bundlewalker doctor PATH`.",
    )
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


def test_diagnostics_contains_toml_integer_limit_as_configuration_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "integer-limit"
    root.mkdir()
    (root / "bundlewalker.toml").write_bytes(b"version = " + b"9" * 5_000 + b"\n")

    result = DiagnosticsApplication(_dependencies()).run(root)
    checks = _by_code(result)

    assert len(result.checks) == 14
    assert checks["workspace.discovery"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.FAILURE
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING


def test_diagnostics_rejects_oversized_config_before_toml_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "oversized"
    root.mkdir()
    (root / "bundlewalker.toml").write_bytes(b"x" * (MAX_WORKSPACE_CONFIG_BYTES + 2))
    original_open = os.open
    original_read = os.read
    config_descriptor: int | None = None
    requested_bytes = 0

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal config_descriptor
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == "bundlewalker.toml" and dir_fd is not None:
            config_descriptor = descriptor
        return descriptor

    def bounded_read(descriptor: int, size: int) -> bytes:
        nonlocal requested_bytes
        if descriptor == config_descriptor:
            requested_bytes += size
            assert requested_bytes <= MAX_WORKSPACE_CONFIG_BYTES + 1
        return original_read(descriptor, size)

    def unexpected_parse(_content: str) -> object:
        pytest.fail("oversized workspace configuration was parsed")

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "read", bounded_read)
        guarded.setattr(tomllib, "loads", unexpected_parse)
        result = DiagnosticsApplication(_dependencies()).run(root)

    checks = _by_code(result)
    assert config_descriptor is not None
    assert requested_bytes <= MAX_WORKSPACE_CONFIG_BYTES + 1
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.FAILURE
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING


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
    status: CompatibilityStatus,
    summary: str,
    remediation_command: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    transaction_calls = 0

    def apply(_quiescent: QuiescentWorkspace) -> None:
        return None

    def verify(_workspace: Workspace) -> None:
        return None

    if status is CompatibilityStatus.UPGRADEABLE:
        target_version = 2
        migrations = {1: MigrationStep(1, 2, apply, verify)}
    else:
        target_version = 1
        migrations = None
        (workspace.root / "bundlewalker.toml").write_text("version = 0\n", encoding="utf-8")

    def count_transaction(_workspace: Workspace) -> TransactionDiagnosticStatus:
        nonlocal transaction_calls
        transaction_calls += 1
        return TransactionDiagnosticStatus.CLEAN

    dependencies = replace(
        _dependencies(),
        transaction_inspector=count_transaction,
        workspace_target_version=target_version,
        workspace_migrations=migrations,
    )

    result = DiagnosticsApplication(dependencies).run(workspace.root)
    checks = _by_code(result)

    assert checks["workspace.configuration"].severity is DiagnosticSeverity.WARNING
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.FAILURE
    assert checks["workspace.compatibility"].summary == summary
    assert remediation_command in " ".join(checks["workspace.compatibility"].remediation)
    assert checks["transactions.state"].severity is DiagnosticSeverity.WARNING
    assert transaction_calls == 0


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


def test_diagnostics_requires_traversal_permission_for_managed_directories(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    checked: list[tuple[Path, int]] = []

    def deny_raw_traversal(path: Path, mode: int) -> bool:
        checked.append((path, mode))
        return not (path == workspace.raw_dir and mode == os.X_OK)

    result = DiagnosticsApplication(
        replace(_dependencies(), permission_check=deny_raw_traversal)
    ).run(workspace.root)

    assert _by_code(result)["workspace.permissions"].severity is DiagnosticSeverity.FAILURE
    assert (workspace.root, os.X_OK) in checked
    assert (workspace.wiki_dir, os.X_OK) in checked
    assert (workspace.raw_dir, os.X_OK) in checked
    assert (workspace.root / "bundlewalker.toml", os.X_OK) not in checked
    assert (workspace.conventions_file, os.X_OK) not in checked


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


def test_diagnostics_support_report_bounds_unexpected_clock_failure(
    tmp_path: Path,
) -> None:
    private_failure = RuntimeError("private clock failure")

    def fail_clock() -> datetime:
        raise private_failure

    application = DiagnosticsApplication(replace(_dependencies(), clock=fail_clock))
    result = application.run(tmp_path)

    with pytest.raises(ApplicationError) as raised:
        application.support_report(result)

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert raised.value.__cause__ is private_failure


def test_diagnostics_support_report_normalizes_clock_application_error(
    tmp_path: Path,
) -> None:
    private_failure = ApplicationError(
        ApplicationErrorCode.INVALID_INPUT,
        "private clock application error",
    )

    def fail_clock() -> datetime:
        raise private_failure

    application = DiagnosticsApplication(replace(_dependencies(), clock=fail_clock))
    result = application.run(tmp_path)

    with pytest.raises(ApplicationError) as raised:
        application.support_report(result)

    assert raised.value is not private_failure
    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert raised.value.__cause__ is private_failure


def test_diagnostics_support_report_bounds_private_validation_failure(
    tmp_path: Path,
) -> None:
    def invalid_clock() -> datetime:
        return cast(datetime, "private-validation-marker")

    application = DiagnosticsApplication(replace(_dependencies(), clock=invalid_clock))
    result = application.run(tmp_path)

    with pytest.raises(ApplicationError) as raised:
        application.support_report(result)

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert isinstance(raised.value.__cause__, ValidationError)
    assert "private-validation-marker" in str(raised.value.__cause__)
    assert "private-validation-marker" not in str(raised.value)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), SystemExit(7)])
def test_diagnostics_support_report_preserves_base_exceptions(
    tmp_path: Path,
    interruption: BaseException,
) -> None:
    def interrupt_clock() -> datetime:
        raise interruption

    application = DiagnosticsApplication(replace(_dependencies(), clock=interrupt_clock))
    result = application.run(tmp_path)

    with pytest.raises(type(interruption)) as raised:
        application.support_report(result)

    assert raised.value is interruption


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
