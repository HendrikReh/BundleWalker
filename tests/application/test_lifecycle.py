# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    BackupResult,
    CompatibilityResult,
    LifecycleApplication,
    LifecycleDependencies,
    RestoreResult,
    UpgradeResult,
)
from bundlewalker.compatibility import CompatibilityStatus, MigrationStep
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_lifecycle_status_inspects_future_format_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text("version = 2\nfuture_path = 'future'\n", encoding="utf-8")

    result = LifecycleApplication().status(root)

    assert result == CompatibilityResult(
        installed_version="0.4.0a1",
        workspace_path=str(root.resolve()),
        workspace_format=2,
        compatibility=CompatibilityStatus.TOO_NEW,
        readable=False,
        writable=False,
        upgrade_available=False,
    )
    assert list(root.iterdir()) == [config]


@pytest.mark.parametrize(
    ("version", "dependencies", "expected_status", "upgrade_available"),
    [
        (0, LifecycleDependencies(), "unsupported", False),
        (
            1,
            LifecycleDependencies(
                target_version=2,
                migrations={
                    1: MigrationStep(
                        1,
                        2,
                        lambda _quiescent: None,
                        lambda _workspace: None,
                    )
                },
            ),
            "upgradeable",
            True,
        ),
    ],
)
def test_lifecycle_status_reports_noncurrent_formats_without_mutation(
    tmp_path: Path,
    version: int,
    dependencies: LifecycleDependencies,
    expected_status: str,
    upgrade_available: bool,
) -> None:
    root = tmp_path / expected_status
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text(f"version = {version}\n", encoding="utf-8")

    result = LifecycleApplication(dependencies).status(root)

    assert result.compatibility == expected_status
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is upgrade_available
    assert list(root.iterdir()) == [config]


def test_lifecycle_backup_and_restore_return_serializable_identity(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    application = LifecycleApplication(
        LifecycleDependencies(clock=lambda: NOW, bundlewalker_version="0.4.0a1")
    )

    backup = application.backup(tmp_path / "knowledge.zip", workspace.root)
    restored = application.restore(Path(backup.archive_path), tmp_path / "restored")

    assert isinstance(backup, BackupResult)
    assert isinstance(restored, RestoreResult)
    assert backup.archive_sha256 == restored.archive_sha256
    assert backup.workspace_format == restored.workspace_format == 1
    assert BackupResult.model_validate_json(backup.model_dump_json()) == backup
    assert RestoreResult.model_validate_json(restored.model_dump_json()) == restored


def test_lifecycle_backup_translates_incompatible_workspace(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    (root / "bundlewalker.toml").write_text("version = 2\n", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication().backup(tmp_path / "future.zip", root)

    assert raised.value.code is ApplicationErrorCode.WORKSPACE_INCOMPATIBLE
    assert raised.value.safe_message == "workspace format is not supported for this operation"
    assert not (tmp_path / "future.zip").exists()


def test_lifecycle_restore_translates_invalid_archive(tmp_path: Path) -> None:
    archive = tmp_path / "private.zip"
    archive.write_bytes(b"not a backup")

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication().restore(archive, tmp_path / "restored")

    assert raised.value.code is ApplicationErrorCode.BACKUP_INVALID
    assert raised.value.safe_message == "backup archive verification failed"
    assert "private" not in raised.value.safe_message
    assert not (tmp_path / "restored").exists()


def test_lifecycle_restore_translates_occupied_target(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication().restore(tmp_path / "unused.zip", target)

    assert raised.value.code is ApplicationErrorCode.RESTORE_TARGET_INVALID
    assert raised.value.safe_message == "restore target must be a new or empty directory"
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_lifecycle_upgrade_current_is_serializable_noop(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    result = LifecycleApplication().upgrade(workspace.root)

    assert result == UpgradeResult(
        status="current",
        workspace_path=str(workspace.root),
        source_version=1,
        target_version=1,
        backup=None,
    )
    assert UpgradeResult.model_validate_json(result.model_dump_json()) == result
    assert list(tmp_path.glob("*.zip")) == []
    assert not (workspace.root / ".bundlewalker").exists()


def test_lifecycle_upgrade_translates_unavailable_path_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "unsupported"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text("version = 0\n", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication().upgrade(root)

    assert raised.value.code is ApplicationErrorCode.MIGRATION_UNAVAILABLE
    assert raised.value.safe_message == "no complete workspace migration path is available"
    assert list(root.iterdir()) == [config]


def test_lifecycle_failed_upgrade_retains_verified_backup_identity(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def fail_after_mutation(quiescent: QuiescentWorkspace) -> None:
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text("version = 2\n", encoding="utf-8")
        raise RuntimeError("token=private-cause")

    dependencies = LifecycleDependencies(
        clock=lambda: NOW,
        target_version=2,
        migrations={
            1: MigrationStep(
                1,
                2,
                fail_after_mutation,
                lambda _workspace: None,
            )
        },
    )

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication(dependencies).upgrade(workspace.root, backup_dir=tmp_path)

    assert raised.value.code is ApplicationErrorCode.MIGRATION_FAILED
    assert raised.value.safe_message == (
        "workspace migration failed; restore the verified pre-upgrade backup"
    )
    assert raised.value.backup_archive_path is not None
    assert Path(raised.value.backup_archive_path).is_file()
    assert raised.value.backup_archive_sha256 is not None
    assert len(raised.value.backup_archive_sha256) == 64
    assert "private-cause" not in raised.value.safe_message
