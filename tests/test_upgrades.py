# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.upgrades as upgrades_module
from bundlewalker.backups import (
    VerifiedBackup,
    restore_workspace_backup,
    verify_backup_archive,
)
from bundlewalker.compatibility import (
    CompatibilityStatus,
    MigrationStep,
    inspect_workspace,
    read_workspace_format_version,
)
from bundlewalker.errors import MigrationExecutionError, MigrationUnavailableError
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.transactions import QuiescentWorkspace, quiescent_workspace
from bundlewalker.upgrades import upgrade_workspace
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_current_upgrade_is_an_exact_noop_without_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_bytes(workspace.root)

    def fail_clock() -> datetime:
        raise AssertionError("a no-op must not consult the migration clock")

    backup_dir = tmp_path / "missing" / "backup-directory"
    outcome = upgrade_workspace(workspace, backup_dir=backup_dir, clock=fail_clock)

    assert outcome.status == "current"
    assert outcome.source_version == 1
    assert outcome.target_version == 1
    assert outcome.backup is None
    assert _tree_bytes(workspace.root) == before
    assert list(tmp_path.glob("*.zip")) == []
    assert not backup_dir.exists()
    assert not (workspace.root / ".bundlewalker").exists()


def test_synthetic_migration_creates_verified_backup_before_apply(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    events: list[str] = []

    def apply(quiescent: QuiescentWorkspace) -> None:
        archives = list(tmp_path.glob("*.zip"))
        assert len(archives) == 1
        verify_backup_archive(archives[0])
        events.append("apply")
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("version = 1", "version = 2"),
            encoding="utf-8",
        )

    def verify(candidate: Workspace) -> None:
        events.append("verify")
        assert "version = 2" in (candidate.root / "bundlewalker.toml").read_text(encoding="utf-8")

    outcome = upgrade_workspace(
        workspace,
        backup_dir=tmp_path,
        target_version=2,
        migrations={1: MigrationStep(1, 2, apply, verify)},
        clock=lambda: NOW,
    )

    assert outcome.status == "upgraded"
    assert outcome.backup is not None
    assert events == ["apply", "verify"]


def test_failed_migration_reports_restorable_preupgrade_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    original = _tree_bytes(workspace.root)

    def fail(quiescent: QuiescentWorkspace) -> None:
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text("version = 2\n", encoding="utf-8")
        raise OSError("simulated migration failure")

    step = MigrationStep(1, 2, fail, lambda _workspace: None)
    with pytest.raises(MigrationExecutionError) as raised:
        upgrade_workspace(
            workspace,
            backup_dir=tmp_path,
            target_version=2,
            migrations={1: step},
            clock=lambda: NOW,
        )

    backup = raised.value.backup
    assert backup is not None
    assert verify_backup_archive(backup.archive_path) == backup
    assert (workspace.root / "bundlewalker.toml").read_bytes() == b"version = 2\n"
    restored = restore_workspace_backup(backup.archive_path, tmp_path / "rollback")
    assert _tree_bytes(restored.workspace.root) == original
    compatibility = inspect_workspace(restored.workspace.root)
    assert compatibility.status is CompatibilityStatus.CURRENT
    assert compatibility.readable is True
    assert compatibility.writable is True
    deterministic_findings = lint_bundle(
        restored.workspace.wiki_dir,
        restored.workspace.root,
    )
    assert not has_errors(deterministic_findings)


def test_incomplete_path_refuses_before_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_bytes(workspace.root)

    def fail_clock() -> datetime:
        raise AssertionError("an unavailable path must not consult the migration clock")

    with pytest.raises(MigrationUnavailableError):
        upgrade_workspace(
            workspace,
            backup_dir=tmp_path,
            target_version=2,
            migrations={},
            clock=fail_clock,
        )

    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()
    assert list(tmp_path.glob("*.zip")) == []


@pytest.mark.parametrize(
    ("source_version", "target_version"),
    [(1, 0), (2, 2), (0, 1)],
)
def test_unsupported_upgrade_direction_refuses_before_lock_or_backup(
    tmp_path: Path,
    source_version: int,
    target_version: int,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    config_path = workspace.root / "bundlewalker.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "version = 1", f"version = {source_version}"
        ),
        encoding="utf-8",
    )
    candidate = Workspace(
        workspace.root,
        replace(workspace.config, version=source_version),
    )
    before = _tree_bytes(workspace.root)
    migrations = {0: MigrationStep(0, 1, lambda _quiescent: None, lambda _workspace: None)}

    with pytest.raises(MigrationUnavailableError):
        upgrade_workspace(
            candidate,
            backup_dir=tmp_path,
            target_version=target_version,
            migrations=migrations,
            clock=lambda: NOW,
        )

    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()
    assert list(tmp_path.glob("*.zip")) == []


def test_post_step_version_is_rechecked_after_verification(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def apply(quiescent: QuiescentWorkspace) -> None:
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("version = 1", "version = 2"),
            encoding="utf-8",
        )

    def corrupt_after_verification(candidate: Workspace) -> None:
        config = candidate.root / "bundlewalker.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("version = 2", "version = 3"),
            encoding="utf-8",
        )

    with pytest.raises(MigrationExecutionError) as raised:
        upgrade_workspace(
            workspace,
            backup_dir=tmp_path,
            target_version=2,
            migrations={1: MigrationStep(1, 2, apply, corrupt_after_verification)},
            clock=lambda: NOW,
        )

    assert raised.value.backup is not None
    assert verify_backup_archive(raised.value.backup.archive_path) == raised.value.backup


@pytest.mark.parametrize("failure_phase", ["verify", "invalid_version", "wrong_version"])
def test_execution_failures_retain_the_verified_backup(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def apply(quiescent: QuiescentWorkspace) -> None:
        config = quiescent.workspace.root / "bundlewalker.toml"
        if failure_phase == "invalid_version":
            config.write_text("not valid toml", encoding="utf-8")
        elif failure_phase != "wrong_version":
            config.write_text(
                config.read_text(encoding="utf-8").replace("version = 1", "version = 2"),
                encoding="utf-8",
            )

    def verify(_workspace: Workspace) -> None:
        if failure_phase == "verify":
            raise RuntimeError("simulated verification failure")

    with pytest.raises(MigrationExecutionError) as raised:
        upgrade_workspace(
            workspace,
            backup_dir=tmp_path,
            target_version=2,
            migrations={1: MigrationStep(1, 2, apply, verify)},
            clock=lambda: NOW,
        )

    backup = raised.value.backup
    assert backup is not None
    assert verify_backup_archive(backup.archive_path) == backup


def test_one_lock_spans_backup_and_contiguous_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    events: list[str] = []
    original_guard = quiescent_workspace
    original_backup = upgrades_module.create_quiescent_backup

    @contextmanager
    def checked_guard(candidate: Workspace) -> Generator[QuiescentWorkspace]:
        events.append("guard-enter")
        with original_guard(candidate) as quiescent:
            yield quiescent
        events.append("guard-exit")

    def checked_backup(
        quiescent: QuiescentWorkspace,
        output: Path,
        *,
        clock: Callable[[], datetime],
    ) -> VerifiedBackup:
        _assert_workspace_locked(quiescent.workspace)
        events.append("backup")
        return original_backup(quiescent, output, clock=clock)

    def step(source: int, target: int) -> MigrationStep:
        def apply(quiescent: QuiescentWorkspace) -> None:
            _assert_workspace_locked(quiescent.workspace)
            assert list(tmp_path.glob("*.zip"))
            events.append(f"apply-{source}-{target}")
            _write_version(quiescent.workspace, source, target)

        def verify(candidate: Workspace) -> None:
            _assert_workspace_locked(candidate)
            assert read_workspace_format_version(candidate.root / "bundlewalker.toml") == target
            events.append(f"verify-{source}-{target}")

        return MigrationStep(source, target, apply, verify)

    monkeypatch.setattr(upgrades_module, "quiescent_workspace", checked_guard)
    monkeypatch.setattr(upgrades_module, "create_quiescent_backup", checked_backup)

    outcome = upgrade_workspace(
        workspace,
        backup_dir=tmp_path,
        target_version=3,
        migrations={1: step(1, 2), 2: step(2, 3)},
        clock=lambda: NOW,
    )

    assert outcome.status == "upgraded"
    assert events == [
        "guard-enter",
        "backup",
        "apply-1-2",
        "verify-1-2",
        "apply-2-3",
        "verify-2-3",
        "guard-exit",
    ]
    _assert_workspace_unlocked(workspace)


def test_preupgrade_backup_name_is_deterministic(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    outcome = upgrade_workspace(
        workspace,
        backup_dir=tmp_path,
        target_version=2,
        migrations={1: _publishing_step(1, 2)},
        clock=lambda: NOW,
    )

    assert outcome.backup is not None
    assert outcome.backup.archive_path.name == (
        "knowledge-pre-upgrade-v1-to-v2-20260718T120000.000000Z.zip"
    )


def test_preupgrade_backup_name_preserves_an_existing_collision(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    existing = tmp_path / "knowledge-pre-upgrade-v1-to-v2-20260718T120000.000000Z.zip"
    existing.write_bytes(b"keep existing archive")

    outcome = upgrade_workspace(
        workspace,
        backup_dir=tmp_path,
        target_version=2,
        migrations={1: _publishing_step(1, 2)},
        clock=lambda: NOW,
    )

    assert existing.read_bytes() == b"keep existing archive"
    assert outcome.backup is not None
    assert outcome.backup.archive_path.name == (
        "knowledge-pre-upgrade-v1-to-v2-20260718T120000.000000Z-2.zip"
    )
    assert verify_backup_archive(outcome.backup.archive_path) == outcome.backup


def _publishing_step(source_version: int, target_version: int) -> MigrationStep:
    def apply(quiescent: QuiescentWorkspace) -> None:
        _write_version(quiescent.workspace, source_version, target_version)

    return MigrationStep(source_version, target_version, apply, lambda _workspace: None)


def _write_version(workspace: Workspace, source_version: int, target_version: int) -> None:
    config = workspace.root / "bundlewalker.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            f"version = {source_version}", f"version = {target_version}"
        ),
        encoding="utf-8",
    )


def _assert_workspace_locked(workspace: Workspace) -> None:
    descriptor = os.open(workspace.root / ".bundlewalker" / "transaction.lock", os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)


def _assert_workspace_unlocked(workspace: Workspace) -> None:
    descriptor = os.open(workspace.root / ".bundlewalker" / "transaction.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
