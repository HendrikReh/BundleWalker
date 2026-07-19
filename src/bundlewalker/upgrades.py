# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from bundlewalker.backups import VerifiedBackup, create_quiescent_backup
from bundlewalker.compatibility import (
    CURRENT_WORKSPACE_FORMAT,
    MINIMUM_WORKSPACE_FORMAT,
    MigrationStep,
    migration_path,
    read_workspace_format_version,
)
from bundlewalker.errors import MigrationExecutionError, MigrationUnavailableError
from bundlewalker.transactions import quiescent_workspace
from bundlewalker.workspace import CONFIG_FILENAME, Workspace


@dataclass(frozen=True, slots=True)
class UpgradeOutcome:
    status: Literal["current", "upgraded"]
    source_version: int
    target_version: int
    backup: VerifiedBackup | None


def upgrade_workspace(
    workspace: Workspace,
    *,
    backup_dir: Path,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> UpgradeOutcome:
    source_version = workspace.config.version
    if not MINIMUM_WORKSPACE_FORMAT <= source_version <= CURRENT_WORKSPACE_FORMAT:
        raise MigrationUnavailableError("no complete workspace migration path is available")
    path = migration_path(
        source_version,
        target_version=target_version,
        migrations=migrations,
    )
    if source_version == target_version:
        if source_version == CURRENT_WORKSPACE_FORMAT:
            return UpgradeOutcome("current", source_version, target_version, None)
        raise MigrationUnavailableError("no complete workspace migration path is available")
    if path is None or not path:
        raise MigrationUnavailableError("no complete workspace migration path is available")

    observed_at = clock()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise MigrationUnavailableError("migration clock must return a timezone-aware timestamp")
    created_at = observed_at.astimezone(UTC)
    timestamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    backup_directory = backup_dir.expanduser().absolute()
    backup_stem = (
        f"{workspace.root.name}-pre-upgrade-v{source_version}-to-v{target_version}-{timestamp}"
    )
    with quiescent_workspace(workspace) as quiescent:
        backup_path = _available_backup_path(backup_directory, backup_stem)
        backup = create_quiescent_backup(
            quiescent,
            backup_path,
            clock=lambda: created_at,
        )
        try:
            for step in path:
                step.apply(quiescent)
                declared = read_workspace_format_version(workspace.root / CONFIG_FILENAME)
                if declared != step.target_version:
                    raise ValueError("migration did not publish its target workspace version")
                step.verify(workspace)
                verified_version = read_workspace_format_version(workspace.root / CONFIG_FILENAME)
                if verified_version != step.target_version:
                    raise ValueError("migration did not retain its target workspace version")
        except Exception as exc:
            raise MigrationExecutionError(
                "workspace migration failed; restore the verified pre-upgrade backup",
                backup=backup,
            ) from exc
    return UpgradeOutcome("upgraded", source_version, target_version, backup)


def _available_backup_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.zip"
    collision = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = directory / f"{stem}-{collision}.zip"
        collision += 1
    return candidate
