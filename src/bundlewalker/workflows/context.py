# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import stat
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import PurePosixPath

from bundlewalker.errors import WorkspaceError
from bundlewalker.workspace import Workspace


def validate_repository_path(workspace: Workspace) -> None:
    """Verify that the configured wiki path has no linked directory component."""
    wiki_parts = safe_configured_parts(workspace.config.wiki_dir, "configured wiki path")
    with open_workspace_directory(workspace, wiki_parts, "configured wiki path"):
        pass


def safe_configured_parts(value: str, description: str) -> tuple[str, ...]:
    """Split one canonical, workspace-relative configured path."""
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or relative == PurePosixPath(".")
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise WorkspaceError(f"{description} is not a safe workspace-relative path")
    return relative.parts


@contextmanager
def open_workspace_directory(
    workspace: Workspace,
    parts: tuple[str, ...],
    description: str,
) -> Generator[int]:
    """Open a workspace-anchored directory chain without following links."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    traversed: list[str] = []
    try:
        current = os.open(workspace.root, flags)
        descriptors.append(current)
        for part in parts:
            traversed.append(part)
            current = os.open(part, flags, dir_fd=current)
            descriptors.append(current)
    except OSError as exc:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        location = "/".join(traversed) or "."
        raise WorkspaceError(
            f"{description} contains a symlink or non-directory: {location}"
        ) from exc
    try:
        yield current
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def _open_workspace_file(
    workspace: Workspace,
    parts: tuple[str, ...],
    description: str,
) -> Generator[int]:
    with open_workspace_directory(workspace, parts[:-1], description) as parent:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("not a regular file")
        except OSError as exc:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            raise WorkspaceError(
                f"{description} contains a symlink or is not a regular file"
            ) from exc
        try:
            yield descriptor
        finally:
            with suppress(OSError):
                os.close(descriptor)


def read_context(workspace: Workspace, relative_path: str, description: str) -> str:
    """Read one regular UTF-8 workspace context file through anchored descriptors."""
    parts = safe_configured_parts(relative_path, description)
    with _open_workspace_file(workspace, parts, description) as descriptor:
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65_536):
                chunks.append(chunk)
        except OSError as exc:
            raise WorkspaceError(f"could not read {description}") from exc
    try:
        return b"".join(chunks).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceError(f"could not decode {description} as UTF-8") from exc
