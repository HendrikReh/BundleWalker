# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker import __version__
from bundlewalker.application.contracts import (
    BackupResult,
    CompatibilityResult,
    RestoreResult,
    UpgradeResult,
)
from bundlewalker.application.errors import ApplicationError, translate_error
from bundlewalker.backups import VerifiedBackup, create_workspace_backup, restore_workspace_backup
from bundlewalker.compatibility import (
    CURRENT_WORKSPACE_FORMAT,
    CompatibilityStatus,
    MigrationStep,
    inspect_workspace,
)
from bundlewalker.errors import (
    BundleWalkerError,
    MigrationUnavailableError,
    WorkspaceCompatibilityError,
)
from bundlewalker.upgrades import upgrade_workspace
from bundlewalker.workspace import discover_workspace


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _empty_migrations() -> Mapping[int, MigrationStep]:
    return {}


@dataclass(frozen=True, slots=True)
class LifecycleDependencies:
    """Injectable clock, version policy, and migration registry."""

    clock: Callable[[], datetime] = _utc_now
    bundlewalker_version: str = __version__
    target_version: int = CURRENT_WORKSPACE_FORMAT
    migrations: Mapping[int, MigrationStep] = field(default_factory=_empty_migrations)


class LifecycleApplication:
    """Synchronous adapter-neutral workspace lifecycle use cases."""

    def __init__(self, dependencies: LifecycleDependencies | None = None) -> None:
        self.dependencies = dependencies or LifecycleDependencies()

    def status(self, start: Path | None = None) -> CompatibilityResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            return CompatibilityResult(
                installed_version=self.dependencies.bundlewalker_version,
                workspace_path=str(inspected.root),
                workspace_format=inspected.workspace_format_version,
                compatibility=inspected.status,
                readable=inspected.readable,
                writable=inspected.writable,
                upgrade_available=inspected.upgrade_available,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def backup(self, output: Path, start: Path | None = None) -> BackupResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            if inspected.status is not CompatibilityStatus.CURRENT:
                raise WorkspaceCompatibilityError(inspected.status)
            verified = create_workspace_backup(
                discover_workspace(inspected.root),
                output,
                clock=self.dependencies.clock,
                bundlewalker_version=self.dependencies.bundlewalker_version,
            )
            return _backup_result(verified)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def restore(self, archive: Path, target: Path) -> RestoreResult:
        try:
            restored = restore_workspace_backup(archive, target)
            backup = restored.backup
            return RestoreResult(
                target_path=str(restored.workspace.root),
                archive_sha256=backup.archive_sha256,
                workspace_format=backup.manifest.workspace_format_version,
                file_count=backup.file_count,
                byte_count=backup.byte_count,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def upgrade(
        self,
        start: Path | None = None,
        *,
        backup_dir: Path | None = None,
    ) -> UpgradeResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            if inspected.status in {
                CompatibilityStatus.TOO_NEW,
                CompatibilityStatus.UNSUPPORTED,
            }:
                if inspected.workspace_format_version < self.dependencies.target_version:
                    raise MigrationUnavailableError(
                        "no complete workspace migration path is available"
                    )
                raise WorkspaceCompatibilityError(inspected.status)
            workspace = discover_workspace(inspected.root)
            outcome = upgrade_workspace(
                workspace,
                backup_dir=backup_dir or inspected.root.parent,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
                clock=self.dependencies.clock,
            )
            return UpgradeResult(
                status=outcome.status,
                workspace_path=str(inspected.root),
                source_version=outcome.source_version,
                target_version=outcome.target_version,
                backup=_backup_result(outcome.backup) if outcome.backup is not None else None,
            )
        except ApplicationError:
            raise
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc


def _backup_result(verified: VerifiedBackup) -> BackupResult:
    return BackupResult(
        archive_path=str(verified.archive_path),
        archive_sha256=verified.archive_sha256,
        created_at=verified.manifest.created_at,
        workspace_format=verified.manifest.workspace_format_version,
        file_count=verified.file_count,
        byte_count=verified.byte_count,
    )
