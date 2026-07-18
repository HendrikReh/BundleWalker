# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import stat
from pathlib import Path

from bundlewalker.coordination import workspace_lock
from bundlewalker.workspace import initialize_workspace


def test_workspace_lock_creates_one_regular_private_lock(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    with workspace_lock(workspace):
        lock = workspace.root / ".bundlewalker" / "transaction.lock"
        metadata = lock.stat(follow_symlinks=False)
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_mode & 0o077 == 0

    assert lock.is_file()
