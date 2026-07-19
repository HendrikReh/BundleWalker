# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker import __version__
from bundlewalker.application.contracts import (
    DiagnosticCategory,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)
from bundlewalker.application.errors import ApplicationError, ApplicationErrorCode
from bundlewalker.compatibility import CompatibilityStatus, inspect_workspace
from bundlewalker.errors import BundleWalkerError
from bundlewalker.transactions import (
    TransactionDiagnosticStatus,
    inspect_transaction_state,
)
from bundlewalker.workflows.context import (
    open_workspace_directory,
    safe_configured_parts,
)
from bundlewalker.workspace import (
    CONFIG_FILENAME,
    Workspace,
    discover_workspace,
    find_workspace_config,
)

ONE_GIB = 1024**3

_SKIPPED_CONFIGURATION = "Workspace configuration was not checked because discovery failed."
_SKIPPED_COMPATIBILITY = (
    "Workspace compatibility was not checked because configuration is unavailable."
)
_SKIPPED_STRUCTURE = (
    "Workspace structure was not checked because a usable workspace is unavailable."
)
_SKIPPED_PERMISSIONS = (
    "Workspace permissions were not checked because a usable workspace is unavailable."
)
_SKIPPED_TRANSACTIONS = (
    "Transaction state was not checked because a usable workspace is unavailable."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


@dataclass(frozen=True, slots=True)
class DiagnosticsDependencies:
    environment: Mapping[str, str] | None = None
    bundlewalker_version: str = __version__
    python_version: tuple[int, int, int] = (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    platform_name: str = platform.system()
    clock: Callable[[], datetime] = _utc_now
    module_available: Callable[[str], bool] = _module_available
    executable_lookup: Callable[[str], str | None] = shutil.which
    permission_check: Callable[[Path, int], bool] = os.access
    disk_free: Callable[[Path], int] = _disk_free
    transaction_inspector: Callable[[Workspace], TransactionDiagnosticStatus] = (
        inspect_transaction_state
    )


def _check(
    code: str,
    category: DiagnosticCategory,
    severity: DiagnosticSeverity,
    summary: str,
    *remediation: str,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        code=code,
        category=category,
        severity=severity,
        summary=summary,
        remediation=remediation,
    )


def _normalized_platform(name: str) -> str:
    normalized = name.strip().casefold()
    if normalized == "darwin":
        return "macos"
    if normalized in {"linux", "windows"}:
        return normalized
    return "other"


def _result(
    bundlewalker_version: str,
    python_version: tuple[int, int, int],
    platform_name: str,
    checks: tuple[DiagnosticCheck, ...],
) -> DiagnosticResult:
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
        bundlewalker_version=bundlewalker_version.strip() or "unknown",
        python_version=".".join(str(value) for value in python_version),
        platform=_normalized_platform(platform_name),
        counts=counts,
        checks=checks,
    )


def _bundlewalker_check(version: str) -> DiagnosticCheck:
    if version.strip():
        return _check(
            "runtime.bundlewalker",
            DiagnosticCategory.RUNTIME,
            DiagnosticSeverity.PASS,
            "BundleWalker package identity is available.",
        )
    return _check(
        "runtime.bundlewalker",
        DiagnosticCategory.RUNTIME,
        DiagnosticSeverity.FAILURE,
        "BundleWalker package identity is unavailable.",
        "Reinstall BundleWalker in the active Python environment.",
    )


def _python_check(version: tuple[int, int, int]) -> DiagnosticCheck:
    if version[:2] in {(3, 13), (3, 14)}:
        return _check(
            "runtime.python",
            DiagnosticCategory.RUNTIME,
            DiagnosticSeverity.PASS,
            "The active Python version is supported.",
        )
    return _check(
        "runtime.python",
        DiagnosticCategory.RUNTIME,
        DiagnosticSeverity.FAILURE,
        "The active Python version is not supported.",
        "Use Python 3.13 or Python 3.14.",
    )


def _platform_check(name: str) -> DiagnosticCheck:
    if _normalized_platform(name) in {"macos", "linux"}:
        return _check(
            "runtime.platform",
            DiagnosticCategory.RUNTIME,
            DiagnosticSeverity.PASS,
            "The active operating system is supported.",
        )
    return _check(
        "runtime.platform",
        DiagnosticCategory.RUNTIME,
        DiagnosticSeverity.WARNING,
        "The active operating system is experimental or unsupported.",
        "Use macOS or Linux for the supported platform contract.",
    )


def _workspace_checks(
    start: Path | None,
    dependencies: DiagnosticsDependencies,
) -> tuple[tuple[DiagnosticCheck, ...], Workspace | None]:
    try:
        if not _nearest_workspace_config_is_safe(start):
            return _unavailable_workspace_checks(
                _check(
                    "workspace.discovery",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.FAILURE,
                    "No usable BundleWalker workspace was found.",
                    "Run `bundlewalker init PATH` or pass an existing workspace to "
                    "`bundlewalker doctor PATH`.",
                ),
                _SKIPPED_CONFIGURATION,
            )
        find_workspace_config(start)
    except (BundleWalkerError, OSError):
        return _unavailable_workspace_checks(
            _check(
                "workspace.discovery",
                DiagnosticCategory.WORKSPACE,
                DiagnosticSeverity.FAILURE,
                "No usable BundleWalker workspace was found.",
                "Run `bundlewalker init PATH` or pass an existing workspace to "
                "`bundlewalker doctor PATH`.",
            ),
            _SKIPPED_CONFIGURATION,
        )

    discovery_check = _check(
        "workspace.discovery",
        DiagnosticCategory.WORKSPACE,
        DiagnosticSeverity.PASS,
        "A BundleWalker workspace configuration was found.",
    )
    try:
        compatibility = inspect_workspace(start)
    except (BundleWalkerError, OSError):
        return _unavailable_workspace_checks(
            discovery_check,
            "Workspace configuration is invalid or unreadable.",
            configuration_severity=DiagnosticSeverity.FAILURE,
        )

    if compatibility.status is not CompatibilityStatus.CURRENT:
        return (
            (
                discovery_check,
                _check(
                    "workspace.configuration",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.WARNING,
                    "Current-format configuration parsing was not attempted for this workspace.",
                ),
                _compatibility_failure(compatibility.status),
                _check(
                    "workspace.structure",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.WARNING,
                    _SKIPPED_STRUCTURE,
                ),
                _check(
                    "workspace.permissions",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.WARNING,
                    _SKIPPED_PERMISSIONS,
                ),
            ),
            None,
        )

    try:
        workspace = discover_workspace(start)
    except (BundleWalkerError, OSError):
        return _unavailable_workspace_checks(
            discovery_check,
            "Workspace configuration is invalid or unreadable.",
            configuration_severity=DiagnosticSeverity.FAILURE,
        )

    configuration_check = _check(
        "workspace.configuration",
        DiagnosticCategory.WORKSPACE,
        DiagnosticSeverity.PASS,
        "Workspace configuration is valid.",
    )
    compatibility_check = _check(
        "workspace.compatibility",
        DiagnosticCategory.WORKSPACE,
        DiagnosticSeverity.PASS,
        "The workspace format is current.",
    )
    try:
        structure_valid = _workspace_structure_valid(workspace)
    except (BundleWalkerError, OSError):
        structure_valid = False
    if not structure_valid:
        return (
            (
                discovery_check,
                configuration_check,
                compatibility_check,
                _check(
                    "workspace.structure",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.FAILURE,
                    "Workspace structure is missing, linked, or has an unexpected kind.",
                    "Restore the required workspace structure without symlinked managed paths.",
                ),
                _check(
                    "workspace.permissions",
                    DiagnosticCategory.WORKSPACE,
                    DiagnosticSeverity.WARNING,
                    _SKIPPED_PERMISSIONS,
                ),
            ),
            None,
        )

    structure_check = _check(
        "workspace.structure",
        DiagnosticCategory.WORKSPACE,
        DiagnosticSeverity.PASS,
        "Workspace structure is valid.",
    )
    try:
        permissions_valid = _workspace_permissions_valid(workspace, dependencies.permission_check)
    except OSError:
        permissions_valid = False
    permissions_check = (
        _check(
            "workspace.permissions",
            DiagnosticCategory.WORKSPACE,
            DiagnosticSeverity.PASS,
            "Required workspace paths passed non-mutating access checks.",
        )
        if permissions_valid
        else _check(
            "workspace.permissions",
            DiagnosticCategory.WORKSPACE,
            DiagnosticSeverity.FAILURE,
            "Required workspace paths are not readable and writable.",
            "Correct workspace permissions before running write operations.",
        )
    )
    return (
        (
            discovery_check,
            configuration_check,
            compatibility_check,
            structure_check,
            permissions_check,
        ),
        workspace,
    )


def _nearest_workspace_config_is_safe(start: Path | None) -> bool:
    candidate = (start or Path.cwd()).expanduser().resolve(strict=False)
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        try:
            metadata = (directory / CONFIG_FILENAME).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        return stat.S_ISREG(metadata.st_mode)
    return True


def _unavailable_workspace_checks(
    discovery_check: DiagnosticCheck,
    configuration_summary: str,
    *,
    configuration_severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
) -> tuple[tuple[DiagnosticCheck, ...], None]:
    return (
        (
            discovery_check,
            _check(
                "workspace.configuration",
                DiagnosticCategory.WORKSPACE,
                configuration_severity,
                configuration_summary,
                *(
                    ("Restore a valid bundlewalker.toml configuration.",)
                    if configuration_severity is DiagnosticSeverity.FAILURE
                    else ()
                ),
            ),
            _check(
                "workspace.compatibility",
                DiagnosticCategory.WORKSPACE,
                DiagnosticSeverity.WARNING,
                _SKIPPED_COMPATIBILITY,
            ),
            _check(
                "workspace.structure",
                DiagnosticCategory.WORKSPACE,
                DiagnosticSeverity.WARNING,
                _SKIPPED_STRUCTURE,
            ),
            _check(
                "workspace.permissions",
                DiagnosticCategory.WORKSPACE,
                DiagnosticSeverity.WARNING,
                _SKIPPED_PERMISSIONS,
            ),
        ),
        None,
    )


def _compatibility_failure(status: CompatibilityStatus) -> DiagnosticCheck:
    if status is CompatibilityStatus.UPGRADEABLE:
        return _check(
            "workspace.compatibility",
            DiagnosticCategory.WORKSPACE,
            DiagnosticSeverity.FAILURE,
            "The workspace format requires an explicit upgrade.",
            "Run `bundlewalker workspace upgrade PATH` after reviewing the upgrade plan.",
        )
    if status is CompatibilityStatus.TOO_NEW:
        summary = "The workspace format is newer than this BundleWalker version supports."
    else:
        summary = "The workspace format is unsupported."
    return _check(
        "workspace.compatibility",
        DiagnosticCategory.WORKSPACE,
        DiagnosticSeverity.FAILURE,
        summary,
        "Run `bundlewalker workspace status PATH` with a compatible BundleWalker version.",
    )


def _workspace_structure_valid(workspace: Workspace) -> bool:
    root_metadata = workspace.root.lstat()
    if workspace.root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        return False

    config_path = workspace.root / CONFIG_FILENAME
    if not _regular_unlinked_file(config_path):
        return False

    wiki_parts = safe_configured_parts(workspace.config.wiki_dir, "configured wiki path")
    raw_parts = safe_configured_parts(workspace.config.raw_dir, "configured raw path")
    conventions_parts = safe_configured_parts(
        workspace.config.conventions_file, "configured conventions path"
    )
    with open_workspace_directory(workspace, wiki_parts, "configured wiki path"):
        pass
    with open_workspace_directory(workspace, raw_parts, "configured raw path"):
        pass
    with open_workspace_directory(
        workspace,
        conventions_parts[:-1],
        "configured conventions path",
    ):
        pass
    return _regular_unlinked_file(workspace.conventions_file)


def _regular_unlinked_file(path: Path) -> bool:
    metadata = path.lstat()
    return not path.is_symlink() and stat.S_ISREG(metadata.st_mode)


def _workspace_permissions_valid(
    workspace: Workspace,
    permission_check: Callable[[Path, int], bool],
) -> bool:
    required_paths = (
        workspace.root,
        workspace.root / CONFIG_FILENAME,
        workspace.wiki_dir,
        workspace.raw_dir,
        workspace.conventions_file,
    )
    return all(
        permission_check(path, mode) for path in required_paths for mode in (os.R_OK, os.W_OK)
    )


def _configuration_checks(
    environment: Mapping[str, str],
) -> tuple[DiagnosticCheck, DiagnosticCheck]:
    model_present, openai_provider = _model_configuration_facts(
        environment.get("BUNDLEWALKER_MODEL", "")
    )
    if not model_present:
        return (
            _check(
                "configuration.model",
                DiagnosticCategory.CONFIGURATION,
                DiagnosticSeverity.WARNING,
                "No agent model is configured.",
                "Set BUNDLEWALKER_MODEL to a supported provider model.",
            ),
            _check(
                "configuration.credential",
                DiagnosticCategory.CONFIGURATION,
                DiagnosticSeverity.WARNING,
                "Provider credentials were not checked because no model is configured.",
            ),
        )

    model_check = _check(
        "configuration.model",
        DiagnosticCategory.CONFIGURATION,
        DiagnosticSeverity.PASS,
        "An agent model is configured through BUNDLEWALKER_MODEL.",
    )
    if openai_provider:
        if environment.get("OPENAI_API_KEY", "").strip():
            credential_check = _check(
                "configuration.credential",
                DiagnosticCategory.CONFIGURATION,
                DiagnosticSeverity.PASS,
                "The OpenAI credential is configured.",
            )
        else:
            credential_check = _check(
                "configuration.credential",
                DiagnosticCategory.CONFIGURATION,
                DiagnosticSeverity.WARNING,
                "The OpenAI credential is not configured.",
                "Set OPENAI_API_KEY before running model-backed operations.",
            )
    else:
        credential_check = _check(
            "configuration.credential",
            DiagnosticCategory.CONFIGURATION,
            DiagnosticSeverity.WARNING,
            "Credential verification is unavailable for the configured provider.",
            "Review the configured provider documentation for credential requirements.",
        )
    return model_check, credential_check


def _model_configuration_facts(model_value: str) -> tuple[bool, bool]:
    model_present = any(not character.isspace() for character in model_value)
    bounded_prefix = model_value[:32]
    separator_index = bounded_prefix.find(":")
    provider_prefix = (
        bounded_prefix[:separator_index].strip().casefold() if separator_index >= 0 else ""
    )
    return model_present, provider_prefix == "openai"


def _transaction_check(
    workspace: Workspace | None,
    inspector: Callable[[Workspace], TransactionDiagnosticStatus],
) -> DiagnosticCheck:
    if workspace is None:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.WARNING,
            _SKIPPED_TRANSACTIONS,
        )
    try:
        state = inspector(workspace)
    except (BundleWalkerError, OSError):
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.FAILURE,
            "Transaction state could not be inspected safely.",
            "Run a normal BundleWalker workspace command to recover interrupted state.",
        )
    if state is TransactionDiagnosticStatus.CLEAN:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.PASS,
            "No pending or interrupted transaction state was found.",
        )
    if state is TransactionDiagnosticStatus.PENDING:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.WARNING,
            "A valid pending review requires a decision.",
            "Run `bundlewalker review show`.",
            "Run `bundlewalker review apply <REVIEW_ID>` to accept it.",
            "Run `bundlewalker review discard <REVIEW_ID>` to reject it.",
        )
    if state is TransactionDiagnosticStatus.BUSY:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.WARNING,
            "The workspace is busy with another operation.",
            "Rerun `bundlewalker doctor PATH` after the active operation finishes.",
        )
    if state is TransactionDiagnosticStatus.INTERRUPTED:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.FAILURE,
            "Interrupted transaction state requires recovery.",
            "Run a normal BundleWalker workspace command to trigger recovery.",
        )
    if state is TransactionDiagnosticStatus.MALFORMED:
        return _check(
            "transactions.state",
            DiagnosticCategory.TRANSACTIONS,
            DiagnosticSeverity.FAILURE,
            "Transaction state is malformed or ambiguous.",
            "Inspect the workspace with `bundlewalker workspace status PATH`.",
        )
    raise TypeError("transaction inspector returned an invalid status")


def _mcp_package_check(available: Callable[[str], bool]) -> DiagnosticCheck:
    try:
        installed = available("mcp")
    except (ImportError, AttributeError, ValueError):
        installed = False
    if installed:
        return _check(
            "mcp.package",
            DiagnosticCategory.MCP,
            DiagnosticSeverity.PASS,
            "The MCP package is available.",
        )
    return _check(
        "mcp.package",
        DiagnosticCategory.MCP,
        DiagnosticSeverity.FAILURE,
        "The MCP package is unavailable or inconsistent.",
        "Reinstall BundleWalker with its MCP dependencies.",
    )


def _mcp_entrypoint_check(lookup: Callable[[str], str | None]) -> DiagnosticCheck:
    try:
        installed = lookup("bundlewalker-mcp") is not None
    except OSError:
        installed = False
    if installed:
        return _check(
            "mcp.entrypoint",
            DiagnosticCategory.MCP,
            DiagnosticSeverity.PASS,
            "The bundlewalker-mcp entry point is available.",
        )
    return _check(
        "mcp.entrypoint",
        DiagnosticCategory.MCP,
        DiagnosticSeverity.FAILURE,
        "The bundlewalker-mcp entry point is unavailable.",
        "Reinstall BundleWalker in the active Python environment.",
    )


def _storage_check(
    start: Path | None,
    workspace: Workspace | None,
    disk_free: Callable[[Path], int],
) -> DiagnosticCheck:
    target = workspace.root if workspace is not None else start or Path.cwd()
    try:
        free = disk_free(target)
    except OSError:
        return _check(
            "storage.disk",
            DiagnosticCategory.STORAGE,
            DiagnosticSeverity.WARNING,
            "Available disk space could not be inspected.",
            "Check available disk space before running write operations.",
        )
    if free >= ONE_GIB:
        return _check(
            "storage.disk",
            DiagnosticCategory.STORAGE,
            DiagnosticSeverity.PASS,
            "At least 1 GiB of disk space is available.",
        )
    return _check(
        "storage.disk",
        DiagnosticCategory.STORAGE,
        DiagnosticSeverity.WARNING,
        "Less than 1 GiB of disk space is available.",
        "Free disk space before running write operations.",
    )


class DiagnosticsApplication:
    def __init__(self, dependencies: DiagnosticsDependencies | None = None) -> None:
        self.dependencies = dependencies or DiagnosticsDependencies()

    def run(self, start: Path | None = None) -> DiagnosticResult:
        try:
            return self._run(start)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ApplicationErrorCode.DIAGNOSTIC_FAILED,
                "diagnostic operation failed",
            ) from exc

    def _run(self, start: Path | None = None) -> DiagnosticResult:
        environment = (
            os.environ if self.dependencies.environment is None else self.dependencies.environment
        )
        workspace_checks, workspace = _workspace_checks(start, self.dependencies)
        model_check, credential_check = _configuration_checks(environment)
        checks = (
            _bundlewalker_check(self.dependencies.bundlewalker_version),
            _python_check(self.dependencies.python_version),
            _platform_check(self.dependencies.platform_name),
            *workspace_checks,
            model_check,
            credential_check,
            _transaction_check(workspace, self.dependencies.transaction_inspector),
            _mcp_package_check(self.dependencies.module_available),
            _mcp_entrypoint_check(self.dependencies.executable_lookup),
            _storage_check(start, workspace, self.dependencies.disk_free),
        )
        return _result(
            self.dependencies.bundlewalker_version,
            self.dependencies.python_version,
            self.dependencies.platform_name,
            checks,
        )

    def support_report(self, result: DiagnosticResult) -> SupportReport:
        return SupportReport(generated_at=self.dependencies.clock(), result=result)
