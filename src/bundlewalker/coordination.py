# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager, suppress

from bundlewalker.errors import TransactionError
from bundlewalker.workspace import Workspace

LOCK_NAME = "transaction.lock"


@contextmanager
def open_workspace_directory(
    workspace: Workspace,
    parts: tuple[str, ...],
    *,
    label: str,
    create_from: int | None = None,
) -> Generator[int]:
    if any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise TransactionError(f"{label} is not a safe workspace-relative directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    traversed: list[str] = []
    try:
        current = os.open(workspace.root, flags)
        descriptors.append(current)
        for index, part in enumerate(parts):
            traversed.append(part)
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if create_from is None or index < create_from:
                    raise
                with suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=current)
                os.fsync(current)
                child = os.open(part, flags, dir_fd=current)
            descriptors.append(child)
            current = child
    except OSError as exc:
        location = "/".join(traversed) or "."
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        raise TransactionError(f"{label} contains a symlink or non-directory: {location}") from exc
    try:
        yield current
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def workspace_lock(workspace: Workspace) -> Generator[None]:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with open_workspace_directory(
        workspace,
        (".bundlewalker",),
        label="transaction lock parent",
        create_from=0,
    ) as parent_descriptor:
        try:
            try:
                descriptor = os.open(
                    LOCK_NAME,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                os.fsync(parent_descriptor)
            except FileExistsError:
                descriptor = os.open(LOCK_NAME, flags, dir_fd=parent_descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise TransactionError("workspace transaction lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise TransactionError("could not acquire workspace transaction lock") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
