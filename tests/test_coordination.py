# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import errno
import fcntl
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import bundlewalker.coordination as coordination_module
from bundlewalker.coordination import LOCK_NAME, workspace_lock
from bundlewalker.errors import TransactionError
from bundlewalker.workspace import initialize_workspace


def test_workspace_lock_creates_one_regular_private_lock(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    with workspace_lock(workspace):
        lock = workspace.root / ".bundlewalker" / "transaction.lock"
        metadata = lock.stat(follow_symlinks=False)
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_mode & 0o077 == 0

    assert lock.is_file()


def test_workspace_lock_closes_descriptor_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    opened, closed, original_fstat = _track_lock_descriptor(monkeypatch)

    def fail_lock_fstat(descriptor: int) -> os.stat_result:
        if descriptor in opened:
            raise OSError(errno.EIO, "injected lock fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(coordination_module.os, "fstat", fail_lock_fstat)

    with (
        pytest.raises(TransactionError, match="could not acquire"),
        workspace_lock(workspace),
    ):
        pytest.fail("lock metadata failure must prevent entry")

    _assert_lock_descriptor_closed_once(opened, closed, original_fstat)


def test_workspace_lock_closes_descriptor_when_flock_fails_without_unlocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    opened, closed, original_fstat = _track_lock_descriptor(monkeypatch)
    original_flock = fcntl.flock
    operations: list[int] = []

    def fail_lock_acquisition(descriptor: int, operation: int) -> None:
        if descriptor in opened:
            operations.append(operation)
            if operation == fcntl.LOCK_EX:
                raise OSError(errno.EIO, "injected lock acquisition failure")
        original_flock(descriptor, operation)

    monkeypatch.setattr(coordination_module.fcntl, "flock", fail_lock_acquisition)

    with (
        pytest.raises(TransactionError, match="could not acquire"),
        workspace_lock(workspace),
    ):
        pytest.fail("lock acquisition failure must prevent entry")

    assert operations == [fcntl.LOCK_EX]
    _assert_lock_descriptor_closed_once(opened, closed, original_fstat)


def test_workspace_lock_closes_descriptor_for_non_regular_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    opened, closed, original_fstat = _track_lock_descriptor(monkeypatch)

    def report_fifo_metadata(descriptor: int) -> os.stat_result:
        metadata = original_fstat(descriptor)
        if descriptor not in opened:
            return metadata
        return os.stat_result((stat.S_IFIFO | 0o600, *metadata[1:]))

    monkeypatch.setattr(coordination_module.os, "fstat", report_fifo_metadata)

    with (
        pytest.raises(TransactionError, match="not a regular file"),
        workspace_lock(workspace),
    ):
        pytest.fail("non-regular lock metadata must prevent entry")

    _assert_lock_descriptor_closed_once(opened, closed, original_fstat)


def _track_lock_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[int], list[int], Callable[[int], os.stat_result]]:
    original_open = os.open
    original_close = os.close
    original_fstat = os.fstat
    opened: list[int] = []
    closed: list[int] = []

    def track_open(
        path: Any,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == LOCK_NAME:
            opened.append(descriptor)
        return descriptor

    def track_close(descriptor: int) -> None:
        if descriptor in opened:
            closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(coordination_module.os, "open", track_open)
    monkeypatch.setattr(coordination_module.os, "close", track_close)
    return opened, closed, original_fstat


def _assert_lock_descriptor_closed_once(
    opened: list[int],
    closed: list[int],
    original_fstat: Callable[[int], os.stat_result],
) -> None:
    assert len(opened) == 1
    assert closed == opened
    with pytest.raises(OSError) as raised:
        original_fstat(opened[0])
    assert raised.value.errno == errno.EBADF
