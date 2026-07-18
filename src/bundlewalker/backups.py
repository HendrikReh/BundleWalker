# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import shutil
import stat
import struct
import sys
import unicodedata
import zipfile
import zlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from tempfile import mkstemp
from typing import IO, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bundlewalker import __version__
from bundlewalker.compatibility import CURRENT_WORKSPACE_FORMAT
from bundlewalker.errors import (
    BackupError,
    BackupVerificationError,
    BundleWalkerError,
    RestoreTargetError,
)
from bundlewalker.transactions import QuiescentWorkspace, quiescent_workspace
from bundlewalker.workspace import (
    CONFIG_FILENAME,
    MAX_WORKSPACE_CONFIG_BYTES,
    Workspace,
    WorkspaceConfig,
    discover_workspace,
    parse_workspace_config,
)

ARCHIVE_FORMAT = "bundlewalker-workspace-backup"
ARCHIVE_SCHEMA_VERSION = 1
MANIFEST_NAME = "bundlewalker-backup.json"
PAYLOAD_PREFIX = "workspace/"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_BACKUP_ENTRIES = 100_000
MAX_BACKUP_PATH_CHARACTERS = 4_096
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SUPPORTED_ZIP_FLAGS = 0x80E
_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
_EOCD_SIZE = 22
_ZIP64_EOCD_SIZE = 56
_ZIP64_LOCATOR_SIZE = 20
_CENTRAL_DIRECTORY_HEADER_SIZE = 46
_MAX_ZIP_COMMENT_BYTES = 65_535
_MAX_CENTRAL_DIRECTORY_BYTES = MAX_MANIFEST_BYTES + MAX_BACKUP_ENTRIES * 128


class BackupFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1, max_length=MAX_BACKUP_PATH_CHARACTERS)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if _canonical_relative_path(self.path) != self.path:
            raise ValueError("backup file path is not canonical")
        return self


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    archive_format: Literal["bundlewalker-workspace-backup"]
    schema_version: Literal[1]
    created_at: datetime
    bundlewalker_version: str = Field(min_length=1, max_length=128)
    workspace_format_version: int
    directories: tuple[str, ...] = Field(max_length=MAX_BACKUP_ENTRIES)
    files: tuple[BackupFileRecord, ...] = Field(max_length=MAX_BACKUP_ENTRIES)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError("backup timestamp must be UTC")
        if self.workspace_format_version != CURRENT_WORKSPACE_FORMAT:
            raise ValueError("unsupported backup workspace format")
        if len(self.directories) + len(self.files) > MAX_BACKUP_ENTRIES:
            raise ValueError("backup contains too many entries")
        canonical_directories = tuple(_canonical_relative_path(path) for path in self.directories)
        if canonical_directories != self.directories:
            raise ValueError("backup directory paths must be canonical and sorted")
        if tuple(sorted(self.directories)) != self.directories:
            raise ValueError("backup directory paths must be canonical and sorted")
        file_paths = tuple(record.path for record in self.files)
        if tuple(sorted(file_paths)) != file_paths:
            raise ValueError("backup file paths must be canonical and sorted")
        if len(set(self.directories)) != len(self.directories):
            raise ValueError("backup contains duplicate directory paths")
        if len(set(file_paths)) != len(file_paths):
            raise ValueError("backup contains duplicate file paths")
        if set(self.directories) & set(file_paths):
            raise ValueError("backup path is both a file and a directory")
        all_paths = (*self.directories, *file_paths)
        file_path_set = set(file_paths)
        if any(
            any(parent.as_posix() in file_path_set for parent in PurePosixPath(other).parents)
            for other in all_paths
        ):
            raise ValueError("backup file path is an ancestor of another entry")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    archive_path: Path
    archive_sha256: str
    manifest: BackupManifest

    @property
    def file_count(self) -> int:
        return len(self.manifest.files)

    @property
    def byte_count(self) -> int:
        return sum(record.size for record in self.manifest.files)


@dataclass(frozen=True, slots=True)
class RestoredWorkspace:
    workspace: Workspace
    backup: VerifiedBackup


@dataclass(frozen=True, slots=True)
class _ManagedEntry:
    relative: str
    absolute: Path
    is_directory: bool
    state: tuple[int, int, int, int, int, int, int]


@dataclass(slots=True)
class _RestoreStaging:
    container_name: str
    container_descriptor: int
    container_identity: tuple[int, int]
    workspace_name: str
    workspace_descriptor: int
    workspace_identity: tuple[int, int]
    entries: dict[str, tuple[bool, tuple[int, int]]]


@dataclass(frozen=True, slots=True)
class _ExistingRestoreTarget:
    descriptor: int
    identity: tuple[int, int]
    mode: int


def create_workspace_backup(
    workspace: Workspace,
    output: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    bundlewalker_version: str = __version__,
) -> VerifiedBackup:
    with quiescent_workspace(workspace) as quiescent:
        return create_quiescent_backup(
            quiescent,
            output,
            clock=clock,
            bundlewalker_version=bundlewalker_version,
        )


def restore_workspace_backup(archive: Path, target: Path) -> RestoredWorkspace:
    try:
        requested_target = target.expanduser().absolute()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RestoreTargetError("restore target path could not be resolved") from exc
    target_existed = _validate_restore_target(requested_target)
    requested_parent = requested_target.parent
    target_path = requested_target
    parent_descriptor: int | None = None
    parent_identity: tuple[int, int, int] | None = None
    original_target: _ExistingRestoreTarget | None = None
    verified_source: IO[bytes] | None = None
    temporary: Path | None = None
    staging: _RestoreStaging | None = None
    removed_empty_target = False
    completed = False
    try:
        parent_descriptor, parent_identity = _open_restore_parent(requested_parent)
        resolved_parent = _resolve_restore_parent(
            requested_parent,
            parent_descriptor,
            parent_identity,
        )
        target_path = resolved_parent / requested_target.name
        original_target = _capture_restore_target(
            parent_descriptor,
            target_path.name,
            expected_to_exist=target_existed,
        )
        verified = verify_backup_archive(archive)
        verified_source = _open_verified_archive(verified)
        if shutil.disk_usage(target_path.parent).free < verified.byte_count:
            raise BackupError("restore destination has insufficient free space")
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        staging = _create_restore_staging(
            parent_descriptor,
            target_path.name,
        )
        temporary = target_path.parent / staging.container_name / staging.workspace_name
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        _require_staging_bound(parent_descriptor, staging)
        _extract_verified_backup(
            verified,
            staging.workspace_descriptor,
            verified_source,
            staging.entries,
        )
        _require_staging_bound(parent_descriptor, staging)
        _verify_extracted_tree(staging.workspace_descriptor, verified.manifest)
        _require_staging_bound(parent_descriptor, staging)
        restored_workspace = discover_workspace(temporary)
        if (
            restored_workspace.root != temporary
            or restored_workspace.config.version != verified.manifest.workspace_format_version
        ):
            raise BackupVerificationError("restored workspace version does not match manifest")
        _validate_managed_payload(verified.manifest, restored_workspace.config)
        _require_staging_bound(parent_descriptor, staging)
        _verify_extracted_tree(staging.workspace_descriptor, verified.manifest)
        _require_verified_archive_open(verified, verified_source)
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        if target_existed:
            if original_target is None:
                raise RestoreTargetError("restore target changed during restoration")
            _require_original_empty_target(
                parent_descriptor,
                target_path.name,
                original_target,
            )
            os.rmdir(target_path.name, dir_fd=parent_descriptor)
            removed_empty_target = True
        else:
            _require_absent_restore_target(parent_descriptor, target_path.name)
        _require_verified_archive_open(verified, verified_source)
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        _require_staging_bound(parent_descriptor, staging)
        _verify_extracted_tree(staging.workspace_descriptor, verified.manifest)
        _rename_noreplace(
            staging.workspace_name,
            target_path.name,
            staging.container_descriptor,
            parent_descriptor,
        )
        try:
            _require_published_restore(
                parent_descriptor,
                target_path.name,
                staging.workspace_identity,
            )
        except BackupError:
            _recover_untrusted_published_target(
                parent_descriptor,
                target_path.name,
                staging.container_descriptor,
            )
            raise
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        _sync_directory_descriptor(parent_descriptor)
        _require_verified_archive_open(verified, verified_source)
        _require_published_restore(
            parent_descriptor,
            target_path.name,
            staging.workspace_identity,
        )
        _require_restore_parent_stable(
            requested_parent,
            resolved_parent,
            parent_descriptor,
            parent_identity,
        )
        _remove_restore_container_if_empty(parent_descriptor, staging)
        completed = True
        published = Workspace(root=target_path, config=restored_workspace.config)
        return RestoredWorkspace(published, verified)
    except (BackupError, RestoreTargetError):
        raise
    except (
        BundleWalkerError,
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zlib.error,
    ) as exc:
        raise BackupError("workspace restore failed") from exc
    finally:
        if verified_source is not None:
            with suppress(OSError):
                verified_source.close()
        if not completed and parent_descriptor is not None and staging is not None:
            _cleanup_restore_staging(parent_descriptor, staging)
        if removed_empty_target and not completed and parent_descriptor is not None:
            mode = original_target.mode if original_target is not None else 0o700
            _recreate_empty_restore_target(parent_descriptor, target_path.name, mode)
        if original_target is not None:
            with suppress(OSError):
                os.close(original_target.descriptor)
        if staging is not None:
            with suppress(OSError):
                os.close(staging.workspace_descriptor)
            with suppress(OSError):
                os.close(staging.container_descriptor)
        if parent_descriptor is not None:
            with suppress(OSError):
                os.close(parent_descriptor)


def _validate_restore_target(target: Path) -> bool:
    try:
        if not target.name or not target.parent.is_dir() or target.parent.is_symlink():
            raise RestoreTargetError("restore target parent must be a regular directory")
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise RestoreTargetError("restore target must be a new or empty directory")
        if target.is_dir():
            _require_empty_target(target)
            return True
        return False
    except RestoreTargetError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc


def _open_restore_parent(parent: Path) -> tuple[int, tuple[int, int, int]]:
    descriptor: int | None = None
    succeeded = False
    try:
        before = parent.lstat()
        if not stat.S_ISDIR(before.st_mode):
            raise RestoreTargetError("restore target parent must be a regular directory")
        descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
        )
        descriptor_state = os.fstat(descriptor)
        after = parent.lstat()
        identity = _managed_identity(descriptor_state)
        if (
            not stat.S_ISDIR(descriptor_state.st_mode)
            or _managed_identity(before) != identity
            or _managed_identity(after) != identity
        ):
            raise RestoreTargetError("restore target parent changed during inspection")
        succeeded = True
        return descriptor, identity
    except RestoreTargetError:
        raise
    except OSError as exc:
        raise RestoreTargetError("restore target parent could not be inspected") from exc
    finally:
        if descriptor is not None and not succeeded:
            with suppress(OSError):
                os.close(descriptor)


def _capture_restore_target(
    parent_descriptor: int,
    name: str,
    *,
    expected_to_exist: bool,
) -> _ExistingRestoreTarget | None:
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        if expected_to_exist:
            raise RestoreTargetError("restore target changed during inspection") from None
        return None
    except (OSError, ValueError) as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc
    if not expected_to_exist:
        raise RestoreTargetError("restore target changed during inspection")
    if not stat.S_ISDIR(metadata.st_mode):
        raise RestoreTargetError("restore target must be an empty regular directory")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            dir_fd=parent_descriptor,
        )
        descriptor_state = os.fstat(descriptor)
        target = _ExistingRestoreTarget(
            descriptor=descriptor,
            identity=(descriptor_state.st_dev, descriptor_state.st_ino),
            mode=stat.S_IMODE(descriptor_state.st_mode),
        )
        _require_original_empty_target(parent_descriptor, name, target)
        descriptor = None
        return target
    except RestoreTargetError:
        raise
    except (OSError, ValueError) as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _resolve_restore_parent(
    requested_parent: Path,
    descriptor: int,
    identity: tuple[int, int, int],
) -> Path:
    try:
        resolved_parent = requested_parent.resolve(strict=True)
        resolved_state = resolved_parent.lstat()
        descriptor_state = os.fstat(descriptor)
    except OSError as exc:
        raise RestoreTargetError("restore target parent changed during inspection") from exc
    if (
        _managed_identity(resolved_state) != identity
        or _managed_identity(descriptor_state) != identity
    ):
        raise RestoreTargetError("restore target parent changed during inspection")
    return resolved_parent


def _require_restore_parent_stable(
    requested_parent: Path,
    resolved_parent: Path,
    descriptor: int,
    identity: tuple[int, int, int],
) -> None:
    try:
        descriptor_state = os.fstat(descriptor)
        requested_state = requested_parent.lstat()
        resolved_state = resolved_parent.lstat()
        current_resolved = requested_parent.resolve(strict=True)
    except OSError as exc:
        raise RestoreTargetError("restore target parent changed during restoration") from exc
    if (
        not stat.S_ISDIR(descriptor_state.st_mode)
        or not stat.S_ISDIR(requested_state.st_mode)
        or not stat.S_ISDIR(resolved_state.st_mode)
        or _managed_identity(descriptor_state) != identity
        or _managed_identity(requested_state) != identity
        or _managed_identity(resolved_state) != identity
        or current_resolved != resolved_parent
    ):
        raise RestoreTargetError("restore target parent changed during restoration")


def _require_empty_target(target: Path) -> None:
    descriptor: int | None = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        descriptor = os.open(target, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RestoreTargetError("restore target must be an empty regular directory")
        if os.listdir(descriptor):
            raise RestoreTargetError("restore target must be empty")
    except RestoreTargetError:
        raise
    except OSError as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_original_empty_target(
    parent_descriptor: int,
    name: str,
    target: _ExistingRestoreTarget,
) -> None:
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor_state = os.fstat(target.descriptor)
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if any(
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != target.identity
            for metadata in (before, descriptor_state, after)
        ):
            raise RestoreTargetError("restore target changed during restoration")
        if os.listdir(target.descriptor):
            raise RestoreTargetError("restore target must be empty")
    except RestoreTargetError:
        raise
    except OSError as exc:
        raise RestoreTargetError("restore target changed during restoration") from exc


def _require_absent_restore_target(parent_descriptor: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc
    raise RestoreTargetError("restore target appeared during restoration")


def _open_verified_archive(verified: VerifiedBackup) -> IO[bytes]:
    descriptor: int | None = None
    source: IO[bytes] | None = None
    succeeded = False
    try:
        before = verified.archive_path.lstat()
        descriptor = os.open(
            verified.archive_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
        )
        descriptor_state = os.fstat(descriptor)
        after = verified.archive_path.lstat()
        _require_unchanged_archive(descriptor_state, before, after)
        source = os.fdopen(descriptor, "rb")
        descriptor = None
        digest = _file_sha256(source)
        descriptor_after_hash = os.fstat(source.fileno())
        path_after_hash = verified.archive_path.lstat()
        _require_unchanged_archive(
            descriptor_state,
            descriptor_after_hash,
            path_after_hash,
        )
        if digest != verified.archive_sha256:
            raise BackupVerificationError("backup archive changed after verification")
        source.seek(0)
        succeeded = True
        return source
    except BackupVerificationError:
        raise
    except OSError as exc:
        raise BackupVerificationError("backup archive changed after verification") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if source is not None and not succeeded:
            with suppress(OSError):
                source.close()


def _require_verified_archive_open(verified: VerifiedBackup, source: IO[bytes]) -> None:
    try:
        descriptor_before = os.fstat(source.fileno())
        path_before = verified.archive_path.lstat()
        _require_unchanged_archive(descriptor_before, path_before)
        digest = _file_sha256(source)
        descriptor_after = os.fstat(source.fileno())
        path_after = verified.archive_path.lstat()
        _require_unchanged_archive(
            descriptor_before,
            descriptor_after,
            path_before,
            path_after,
        )
        if digest != verified.archive_sha256:
            raise BackupVerificationError("backup archive changed during restoration")
    except BackupVerificationError:
        raise
    except OSError as exc:
        raise BackupVerificationError("backup archive changed during restoration") from exc


def _create_restore_staging(
    parent_descriptor: int,
    target_name: str,
) -> _RestoreStaging:
    for _attempt in range(100):
        container_name = f".{target_name}-restore-{secrets.token_hex(8)}"
        try:
            os.mkdir(container_name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        container_descriptor: int | None = None
        container_identity: tuple[int, int] | None = None
        workspace_descriptor: int | None = None
        workspace_identity: tuple[int, int] | None = None
        workspace_name = "workspace"
        succeeded = False
        try:
            container_descriptor = os.open(
                container_name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0),
                dir_fd=parent_descriptor,
            )
            descriptor_state = os.fstat(container_descriptor)
            container_identity = (descriptor_state.st_dev, descriptor_state.st_ino)
            relative_state = os.stat(
                container_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(descriptor_state.st_mode)
                or not stat.S_ISDIR(relative_state.st_mode)
                or (relative_state.st_dev, relative_state.st_ino) != container_identity
            ):
                raise BackupError("restore staging directory changed during creation")

            os.mkdir(workspace_name, mode=0o700, dir_fd=container_descriptor)
            workspace_descriptor = os.open(
                workspace_name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0),
                dir_fd=container_descriptor,
            )
            workspace_state = os.fstat(workspace_descriptor)
            workspace_identity = (workspace_state.st_dev, workspace_state.st_ino)
            relative_workspace_state = os.stat(
                workspace_name,
                dir_fd=container_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(workspace_state.st_mode)
                or not stat.S_ISDIR(relative_workspace_state.st_mode)
                or (
                    relative_workspace_state.st_dev,
                    relative_workspace_state.st_ino,
                )
                != workspace_identity
            ):
                raise BackupError("restore staging directory changed during creation")
            staging = _RestoreStaging(
                container_name=container_name,
                container_descriptor=container_descriptor,
                container_identity=container_identity,
                workspace_name=workspace_name,
                workspace_descriptor=workspace_descriptor,
                workspace_identity=workspace_identity,
                entries={},
            )
            succeeded = True
            return staging
        except BaseException:
            if container_descriptor is not None and workspace_identity is not None:
                _remove_empty_directory_identity(container_descriptor, workspace_identity)
            if container_identity is not None:
                _remove_empty_directory_identity(parent_descriptor, container_identity)
            raise
        finally:
            if not succeeded and workspace_descriptor is not None:
                with suppress(OSError):
                    os.close(workspace_descriptor)
            if not succeeded and container_descriptor is not None:
                with suppress(OSError):
                    os.close(container_descriptor)
    raise BackupError("restore staging directory could not be allocated")


def _require_staging_bound(
    parent_descriptor: int,
    staging: _RestoreStaging,
) -> None:
    try:
        container_descriptor_state = os.fstat(staging.container_descriptor)
        workspace_descriptor_state = os.fstat(staging.workspace_descriptor)
        container_relative_state = os.stat(
            staging.container_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        workspace_relative_state = os.stat(
            staging.workspace_name,
            dir_fd=staging.container_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise BackupError("restore staging directory changed") from exc
    if any(
        not stat.S_ISDIR(metadata.st_mode)
        for metadata in (
            container_descriptor_state,
            workspace_descriptor_state,
            container_relative_state,
            workspace_relative_state,
        )
    ) or any(
        identity != expected
        for identity, expected in (
            (
                (container_descriptor_state.st_dev, container_descriptor_state.st_ino),
                staging.container_identity,
            ),
            (
                (container_relative_state.st_dev, container_relative_state.st_ino),
                staging.container_identity,
            ),
            (
                (workspace_descriptor_state.st_dev, workspace_descriptor_state.st_ino),
                staging.workspace_identity,
            ),
            (
                (workspace_relative_state.st_dev, workspace_relative_state.st_ino),
                staging.workspace_identity,
            ),
        )
    ):
        raise BackupError("restore staging directory changed")


def _extract_verified_backup(
    verified: VerifiedBackup,
    root_descriptor: int,
    source: IO[bytes],
    entries: dict[str, tuple[bool, tuple[int, int]]],
) -> None:
    with zipfile.ZipFile(source) as archive_file:
        for relative in verified.manifest.directories:
            descriptor = _open_restore_directory(
                root_descriptor,
                PurePosixPath(relative).parts,
                create=True,
                owned_entries=entries,
            )
            try:
                metadata = os.fstat(descriptor)
                entries[relative] = (
                    True,
                    (metadata.st_dev, metadata.st_ino),
                )
                _sync_directory_descriptor(descriptor)
            finally:
                os.close(descriptor)

        for record in verified.manifest.files:
            parts = PurePosixPath(record.path).parts
            parent = _open_restore_directory(
                root_descriptor,
                parts[:-1],
                create=True,
                owned_entries=entries,
            )
            try:
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_BINARY", 0)
                )
                descriptor = os.open(parts[-1], flags, 0o600, dir_fd=parent)
                digest = hashlib.sha256()
                count = 0
                try:
                    metadata = os.fstat(descriptor)
                    entries[record.path] = (
                        False,
                        (metadata.st_dev, metadata.st_ino),
                    )
                    with archive_file.open(f"{PAYLOAD_PREFIX}{record.path}") as member:
                        while chunk := member.read(1024 * 1024):
                            count += len(chunk)
                            if count > record.size:
                                raise BackupVerificationError(
                                    f"backup member exceeds declared size: {record.path}"
                                )
                            digest.update(chunk)
                            view = memoryview(chunk)
                            while view:
                                written = os.write(descriptor, view)
                                if written == 0:
                                    raise OSError("restore write made no progress")
                                view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                if count != record.size or digest.hexdigest() != record.sha256:
                    raise BackupVerificationError(
                        f"restored member identity mismatch: {record.path}"
                    )
                _sync_directory_descriptor(parent)
            finally:
                os.close(parent)
    _sync_directory_descriptor(root_descriptor)


def _open_restore_directory(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    create: bool,
    owned_entries: dict[str, tuple[bool, tuple[int, int]]] | None = None,
    parent_path: PurePosixPath | None = None,
) -> int:
    current = os.dup(root_descriptor)
    current_path = parent_path or PurePosixPath()
    try:
        for part in parts:
            created = False
            current_path /= part
            trusted_identity: tuple[int, int] | None = None
            if create:
                if owned_entries is None:
                    raise BackupVerificationError("restore staging ownership is unavailable")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                    created = True
                except FileExistsError:
                    expected = owned_entries.get(current_path.as_posix())
                    if expected is None or not expected[0]:
                        raise BackupVerificationError(
                            "restore staging path was not created by BundleWalker"
                        ) from None
                    trusted_identity = expected[1]
                else:
                    created_state = os.stat(
                        part,
                        dir_fd=current,
                        follow_symlinks=False,
                    )
                    if not stat.S_ISDIR(created_state.st_mode):
                        raise BackupVerificationError(
                            "restore staging path changed during extraction"
                        )
                    trusted_identity = (created_state.st_dev, created_state.st_ino)
                    owned_entries[current_path.as_posix()] = (True, trusted_identity)
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0),
                dir_fd=current,
            )
            child_state = os.fstat(child)
            relative_state = os.stat(part, dir_fd=current, follow_symlinks=False)
            child_identity = (child_state.st_dev, child_state.st_ino)
            if (
                not stat.S_ISDIR(child_state.st_mode)
                or _managed_identity(child_state) != _managed_identity(relative_state)
                or (trusted_identity is not None and child_identity != trusted_identity)
            ):
                os.close(child)
                raise BackupVerificationError("restore staging path changed during extraction")
            if created:
                _sync_directory_descriptor(current)
            os.close(current)
            current = child
        return current
    except BaseException:
        with suppress(OSError):
            os.close(current)
        raise


def _verify_extracted_tree(root_descriptor: int, manifest: BackupManifest) -> None:
    descriptor = os.dup(root_descriptor)
    try:
        expected_files = {record.path: record for record in manifest.files}
        actual_files: set[str] = set()
        actual_directories: set[str] = set()
        _walk_extracted_tree(
            descriptor,
            PurePosixPath(),
            expected_files,
            actual_files,
            actual_directories,
        )
        if actual_files != set(expected_files) or actual_directories != set(manifest.directories):
            raise BackupVerificationError("restored workspace entries do not match manifest")
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _walk_extracted_tree(
    directory_descriptor: int,
    parent: PurePosixPath,
    expected_files: dict[str, BackupFileRecord],
    actual_files: set[str],
    actual_directories: set[str],
) -> None:
    for name in sorted(os.listdir(directory_descriptor)):
        path = parent / name
        relative = path.as_posix()
        metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(relative)
            child = _open_restore_directory(
                directory_descriptor,
                (name,),
                create=False,
            )
            try:
                _walk_extracted_tree(
                    child,
                    path,
                    expected_files,
                    actual_files,
                    actual_directories,
                )
            finally:
                os.close(child)
        elif stat.S_ISREG(metadata.st_mode):
            actual_files.add(relative)
            record = expected_files.get(relative)
            if record is None:
                raise BackupVerificationError("restored workspace file identity mismatch")
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                dir_fd=directory_descriptor,
            )
            try:
                descriptor_state = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(descriptor_state.st_mode)
                    or _managed_identity(descriptor_state) != _managed_identity(metadata)
                    or descriptor_state.st_size != record.size
                ):
                    raise BackupVerificationError("restored workspace file identity mismatch")
                with os.fdopen(os.dup(descriptor), "rb") as restored_file:
                    digest = _file_sha256(restored_file)
                after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if digest != record.sha256 or _managed_state(after) != _managed_state(
                    descriptor_state
                ):
                    raise BackupVerificationError("restored workspace file identity mismatch")
            finally:
                os.close(descriptor)
        else:
            raise BackupVerificationError("restored workspace contains a special file")


def _rename_noreplace(
    source: str,
    destination: str,
    source_descriptor: int,
    destination_descriptor: int,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        try:
            rename = library.renameatx_np
        except AttributeError as exc:
            raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from exc
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_descriptor,
            source_bytes,
            destination_descriptor,
            destination_bytes,
            0x00000004,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = library.renameat2
        except AttributeError as exc:
            raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from exc
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_descriptor,
            source_bytes,
            destination_descriptor,
            destination_bytes,
            0x00000001,
        )
    else:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def _require_published_restore(
    parent_descriptor: int,
    name: str,
    identity: tuple[int, int],
) -> None:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            dir_fd=parent_descriptor,
        )
        descriptor_state = os.fstat(descriptor)
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if any(
            not stat.S_ISDIR(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != identity
            for metadata in (before, descriptor_state, after)
        ):
            raise BackupError("restored workspace changed during publication")
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("restored workspace changed during publication") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _recover_untrusted_published_target(
    parent_descriptor: int,
    target_name: str,
    container_descriptor: int,
) -> None:
    try:
        os.stat(target_name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BackupError("untrusted publication could not be preserved") from exc
    for _attempt in range(100):
        recovery_name = f"actor-recovery-{secrets.token_hex(8)}"
        try:
            _rename_noreplace(
                target_name,
                recovery_name,
                parent_descriptor,
                container_descriptor,
            )
            return
        except FileExistsError:
            continue
        except OSError as exc:
            raise BackupError("untrusted publication could not be preserved") from exc
    raise BackupError("untrusted publication could not be preserved")


def _cleanup_restore_staging(
    parent_descriptor: int,
    staging: _RestoreStaging,
) -> None:
    with suppress(OSError):
        _clear_owned_restore_directory(
            staging.workspace_descriptor,
            PurePosixPath(),
            staging.entries,
        )
    with suppress(OSError):
        _remove_empty_directory_identity(
            staging.container_descriptor,
            staging.workspace_identity,
        )
    with suppress(OSError):
        _remove_empty_directory_identity(parent_descriptor, staging.workspace_identity)
    with suppress(OSError):
        _remove_restore_container_if_empty(parent_descriptor, staging)


def _clear_owned_restore_directory(
    directory_descriptor: int,
    parent: PurePosixPath,
    entries: dict[str, tuple[bool, tuple[int, int]]],
) -> None:
    for name in os.listdir(directory_descriptor):
        relative = (parent / name).as_posix()
        expected = entries.get(relative)
        if expected is None:
            continue
        expected_directory, expected_identity = expected
        try:
            metadata = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            continue
        actual_identity = (metadata.st_dev, metadata.st_ino)
        if (
            actual_identity != expected_identity
            or stat.S_ISDIR(metadata.st_mode) != expected_directory
        ):
            continue
        if expected_directory:
            try:
                child = _open_restore_directory(
                    directory_descriptor,
                    (name,),
                    create=False,
                )
            except (OSError, BackupVerificationError):
                continue
            try:
                _clear_owned_restore_directory(child, parent / name, entries)
            finally:
                with suppress(OSError):
                    os.close(child)
            _remove_empty_directory_identity(directory_descriptor, expected_identity)
        else:
            try:
                before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                descriptor = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                    dir_fd=directory_descriptor,
                )
            except OSError:
                continue
            try:
                descriptor_state = os.fstat(descriptor)
                after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if all(
                    stat.S_ISREG(state.st_mode)
                    and (state.st_dev, state.st_ino) == expected_identity
                    for state in (before, descriptor_state, after)
                ):
                    os.unlink(name, dir_fd=directory_descriptor)
            except OSError:
                continue
            finally:
                with suppress(OSError):
                    os.close(descriptor)


def _remove_empty_directory_identity(
    parent_descriptor: int,
    identity: tuple[int, int],
) -> None:
    for _attempt in range(100):
        matched_name: str | None = None
        for name in os.listdir(parent_descriptor):
            try:
                metadata = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                continue
            if stat.S_ISDIR(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == identity:
                matched_name = name
                break
        if matched_name is None:
            return
        try:
            os.rmdir(matched_name, dir_fd=parent_descriptor)
            return
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            try:
                current = os.stat(
                    matched_name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                continue
            if (current.st_dev, current.st_ino) == identity:
                return


def _remove_restore_container_if_empty(
    parent_descriptor: int,
    staging: _RestoreStaging,
) -> None:
    if os.listdir(staging.container_descriptor):
        return
    _remove_empty_directory_identity(parent_descriptor, staging.container_identity)


def _recreate_empty_restore_target(
    parent_descriptor: int,
    name: str,
    mode: int,
) -> None:
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_descriptor)
        os.chmod(name, mode, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError:
        return


def create_quiescent_backup(
    quiescent: QuiescentWorkspace,
    output: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    bundlewalker_version: str = __version__,
) -> VerifiedBackup:
    workspace = quiescent.workspace
    output_path: Path | None = None
    temporary: Path | None = None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    temporary_archive_state: tuple[int, int, int, int, int, int, int] | None = None
    output_parent_descriptor: int | None = None
    output_parent_identity: tuple[int, int, int] | None = None
    published_identity: tuple[int, int] | None = None
    completed = False
    try:
        output_path = output.expanduser().absolute()
        resolved_output = output_path.resolve(strict=False)
        workspace_root = workspace.root.resolve(strict=True)
        if resolved_output == workspace_root or resolved_output.is_relative_to(workspace_root):
            raise BackupError("backup output must be outside the workspace")
        if output_path.exists() or output_path.is_symlink():
            raise BackupError("backup output already exists")
        if not output_path.parent.is_dir() or output_path.parent.is_symlink():
            raise BackupError("backup output parent must be a regular directory")
        output_parent_descriptor = os.open(
            output_path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent_descriptor_state = os.fstat(output_parent_descriptor)
        output_parent_identity = _managed_identity(parent_descriptor_state)
        _require_output_parent_stable(
            output_path,
            output_parent_descriptor,
            output_parent_identity,
            resolved_output=resolved_output,
            workspace_root=workspace_root,
        )
        if workspace.config.version != CURRENT_WORKSPACE_FORMAT:
            raise BackupError("workspace is not current")
        try:
            entries = _managed_entries(workspace)
            file_entries = tuple(entry for entry in entries if not entry.is_directory)
            byte_count = sum(entry.absolute.lstat().st_size for entry in file_entries)
        except OSError as exc:
            raise BackupError("workspace backup could not read managed data") from exc
        if shutil.disk_usage(output_path.parent).free < byte_count:
            raise BackupError("backup destination has insufficient free space")
        observed_at = clock()
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
            observed_at, datetime
        ):
            raise BackupError("backup clock must return a timezone-aware timestamp")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise BackupError("backup clock must return a timezone-aware timestamp")
        created_at = observed_at.astimezone(UTC)
        descriptor, temporary_name = mkstemp(
            prefix=".bundlewalker-backup-",
            dir=output_path.parent,
        )
        temporary = Path(temporary_name)
        temporary_name = temporary.name
        try:
            descriptor_state = os.fstat(descriptor)
            temporary_identity = (descriptor_state.st_dev, descriptor_state.st_ino)
            os.fchmod(descriptor, 0o600)
            descriptor_state = os.fstat(descriptor)
            relative_state = os.stat(
                temporary_name,
                dir_fd=output_parent_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(descriptor_state.st_mode) or _managed_identity(
                descriptor_state
            ) != _managed_identity(relative_state):
                raise BackupError("backup temporary output changed during creation")
            with os.fdopen(descriptor, "w+b") as temporary_file:
                descriptor = -1
                records: list[BackupFileRecord] = []
                with zipfile.ZipFile(
                    temporary_file,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    allowZip64=True,
                ) as archive:
                    for entry in entries:
                        if entry.is_directory:
                            archive.writestr(
                                _archive_info(entry.relative, is_directory=True),
                                b"",
                            )
                    for entry in file_entries:
                        try:
                            records.append(_stream_stable_file(archive, entry))
                        except OSError as exc:
                            raise BackupError(
                                "workspace backup could not read managed data"
                            ) from exc
                    try:
                        _require_managed_entries_stable(entries)
                    except OSError as exc:
                        raise BackupError("workspace backup could not read managed data") from exc
                    manifest = BackupManifest(
                        archive_format=ARCHIVE_FORMAT,
                        schema_version=ARCHIVE_SCHEMA_VERSION,
                        created_at=created_at,
                        bundlewalker_version=bundlewalker_version,
                        workspace_format_version=workspace.config.version,
                        directories=tuple(
                            entry.relative for entry in entries if entry.is_directory
                        ),
                        files=tuple(records),
                    )
                    archive.writestr(
                        _archive_info(MANIFEST_NAME, payload_prefix=False),
                        manifest.model_dump_json(indent=2) + "\n",
                    )
                temporary_file.flush()
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
        archive_state = os.stat(
            temporary_name,
            dir_fd=output_parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(archive_state.st_mode)
            or (archive_state.st_dev, archive_state.st_ino) != temporary_identity
        ):
            raise BackupError("backup temporary output changed during creation")
        temporary_archive_state = _managed_state(archive_state)
        verified = verify_backup_archive(temporary)
        _require_output_parent_stable(
            output_path,
            output_parent_descriptor,
            output_parent_identity,
            resolved_output=resolved_output,
            workspace_root=workspace_root,
        )
        sync_descriptor: int | None = None
        try:
            sync_descriptor = os.open(
                temporary_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=output_parent_descriptor,
            )
            sync_state = os.fstat(sync_descriptor)
            if (
                not stat.S_ISREG(sync_state.st_mode)
                or _managed_state(sync_state) != temporary_archive_state
            ):
                raise BackupError("backup temporary output changed after verification")
            os.fsync(sync_descriptor)
            try:
                os.link(
                    temporary_name,
                    output_path.name,
                    src_dir_fd=output_parent_descriptor,
                    dst_dir_fd=output_parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise BackupError("backup output already exists") from exc
            published_identity = temporary_identity
            published_state = os.stat(
                output_path.name,
                dir_fd=output_parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(published_state.st_mode)
                or (published_state.st_dev, published_state.st_ino) != published_identity
            ):
                raise BackupError("backup output changed during publication")
            hash_before = os.fstat(sync_descriptor)
            with os.fdopen(os.dup(sync_descriptor), "rb") as published_source:
                published_sha256 = _file_sha256(published_source)
            hash_after = os.fstat(sync_descriptor)
            final_output_state = os.stat(
                output_path.name,
                dir_fd=output_parent_descriptor,
                follow_symlinks=False,
            )
            if (
                _managed_state(hash_before) != _managed_state(hash_after)
                or _managed_state(hash_after) != _managed_state(final_output_state)
                or published_sha256 != verified.archive_sha256
            ):
                raise BackupError("backup output changed during publication")
            _require_output_parent_stable(
                output_path,
                output_parent_descriptor,
                output_parent_identity,
                resolved_output=resolved_output,
                workspace_root=workspace_root,
            )
            _sync_directory_descriptor(output_parent_descriptor)
            _require_output_parent_stable(
                output_path,
                output_parent_descriptor,
                output_parent_identity,
                resolved_output=resolved_output,
                workspace_root=workspace_root,
            )
            completed = True
            return VerifiedBackup(output_path, verified.archive_sha256, verified.manifest)
        finally:
            if sync_descriptor is not None:
                with suppress(OSError):
                    os.close(sync_descriptor)
    except BackupError:
        raise
    except (BundleWalkerError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise BackupError("workspace backup creation failed") from exc
    finally:
        removed_temporary = False
        if (
            output_parent_descriptor is not None
            and temporary_name is not None
            and temporary_identity is not None
        ):
            removed_temporary = _unlink_owned_entry(
                temporary_name,
                temporary_identity,
                dir_fd=output_parent_descriptor,
            )
        if not removed_temporary and temporary is not None and temporary_identity is not None:
            _unlink_owned_entry(temporary, temporary_identity)
        if not completed and output_path is not None and published_identity is not None:
            removed_output = False
            if output_parent_descriptor is not None:
                removed_output = _unlink_owned_entry(
                    output_path.name,
                    published_identity,
                    dir_fd=output_parent_descriptor,
                )
            if not removed_output:
                _unlink_owned_entry(output_path, published_identity)
        if output_parent_descriptor is not None:
            with suppress(OSError):
                os.close(output_parent_descriptor)


def _managed_entries(workspace: Workspace) -> tuple[_ManagedEntry, ...]:
    file_roots = (
        PurePosixPath(CONFIG_FILENAME),
        PurePosixPath(workspace.config.conventions_file),
    )
    directory_roots = (
        PurePosixPath(workspace.config.raw_dir),
        PurePosixPath(workspace.config.wiki_dir),
    )
    roots = (*file_roots, *directory_roots)
    for path in roots:
        try:
            _canonical_relative_path(path.as_posix())
        except ValueError as exc:
            raise BackupError("configured managed path is unsafe") from exc
    reserved_key = _portable_path_component(".bundlewalker")
    if any(
        path.parts and _portable_path_component(path.parts[0]) == reserved_key for path in roots
    ):
        raise BackupError("configured managed path overlaps reserved internal state")
    entries: dict[str, _ManagedEntry] = {}

    def add(candidate: Path) -> None:
        relative = candidate.relative_to(workspace.root).as_posix()
        _canonical_relative_path(relative)
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise BackupError(f"managed path is a symlink: {relative}")
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise BackupError(f"managed path is not a regular file or directory: {relative}")
        incoming = _ManagedEntry(
            relative,
            candidate,
            stat.S_ISDIR(metadata.st_mode),
            _managed_state(metadata),
        )
        existing = entries.get(relative)
        if existing is not None and existing.is_directory != incoming.is_directory:
            raise BackupError(f"managed path changes type: {relative}")
        entries[relative] = incoming

    for relative_root in roots:
        for parent in reversed(relative_root.parents):
            if parent != PurePosixPath("."):
                add(workspace.root.joinpath(*parent.parts))
        absolute_root = workspace.root.joinpath(*relative_root.parts)
        add(absolute_root)
        for candidate in sorted(absolute_root.rglob("*")):
            add(candidate)
    return tuple(entries[path] for path in sorted(entries))


def _stream_stable_file(
    archive: zipfile.ZipFile,
    entry: _ManagedEntry,
) -> BackupFileRecord:
    parts = PurePosixPath(entry.relative).parts
    workspace_root = entry.absolute
    for _part in parts:
        workspace_root = workspace_root.parent
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    directory_descriptors: list[tuple[Path, int, tuple[int, int, int]]] = []
    descriptor: int | None = None
    digest = hashlib.sha256()
    count = 0
    try:
        root_before = workspace_root.lstat()
        current = os.open(workspace_root, directory_flags)
        directory_descriptors.append((workspace_root, current, (0, 0, 0)))
        root_descriptor = os.fstat(current)
        root_after = workspace_root.lstat()
        _require_stable_directory_identity(
            root_descriptor,
            root_before,
            root_after,
        )
        directory_descriptors[-1] = (
            workspace_root,
            current,
            _managed_identity(root_descriptor),
        )
        traversed = workspace_root
        for part in parts[:-1]:
            traversed /= part
            relative_before = os.stat(part, dir_fd=current, follow_symlinks=False)
            absolute_before = traversed.lstat()
            child = os.open(part, directory_flags, dir_fd=current)
            directory_descriptors.append((traversed, child, (0, 0, 0)))
            child_descriptor = os.fstat(child)
            relative_after = os.stat(part, dir_fd=current, follow_symlinks=False)
            absolute_after = traversed.lstat()
            _require_stable_directory_identity(
                child_descriptor,
                relative_before,
                absolute_before,
                relative_after,
                absolute_after,
            )
            directory_descriptors[-1] = (
                traversed,
                child,
                _managed_identity(child_descriptor),
            )
            current = child
        filename = parts[-1]
        path_before = os.stat(filename, dir_fd=current, follow_symlinks=False)
        absolute_before = entry.absolute.lstat()
        descriptor = os.open(filename, file_flags, dir_fd=current)
        descriptor_before = os.fstat(descriptor)
        path_after_open = os.stat(filename, dir_fd=current, follow_symlinks=False)
        absolute_after_open = entry.absolute.lstat()
        snapshots_before = (
            path_before,
            absolute_before,
            descriptor_before,
            path_after_open,
            absolute_after_open,
        )
        if any(
            not stat.S_ISREG(snapshot.st_mode) or _managed_state(snapshot) != entry.state
            for snapshot in snapshots_before
        ):
            raise BackupError("managed backup entry changed before it was read")
        if not stat.S_ISREG(descriptor_before.st_mode):
            raise BackupError("managed backup entry is not a regular file")
        with archive.open(_archive_info(entry.relative), "w", force_zip64=True) as destination:
            while chunk := os.read(descriptor, 1024 * 1024):
                count += len(chunk)
                digest.update(chunk)
                destination.write(chunk)
        descriptor_after = os.fstat(descriptor)
        path_after = os.stat(filename, dir_fd=current, follow_symlinks=False)
        absolute_after = entry.absolute.lstat()
        snapshots_after = (descriptor_after, path_after, absolute_after)
        if any(
            not stat.S_ISREG(snapshot.st_mode) or _managed_state(snapshot) != entry.state
            for snapshot in snapshots_after
        ):
            raise BackupError("managed backup entry changed while it was read")
        for directory_path, directory_descriptor, identity in directory_descriptors:
            descriptor_state = os.fstat(directory_descriptor)
            path_state = directory_path.lstat()
            if (
                not stat.S_ISDIR(descriptor_state.st_mode)
                or not stat.S_ISDIR(path_state.st_mode)
                or _managed_identity(descriptor_state) != identity
                or _managed_identity(path_state) != identity
            ):
                raise BackupError("managed backup path changed while it was read")
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        for _path, directory_descriptor, _identity in reversed(directory_descriptors):
            with suppress(OSError):
                os.close(directory_descriptor)
    if count != descriptor_after.st_size:
        raise BackupError("managed backup entry size changed while it was read")
    return BackupFileRecord(
        path=entry.relative,
        size=count,
        sha256=digest.hexdigest(),
    )


def _require_managed_entries_stable(entries: tuple[_ManagedEntry, ...]) -> None:
    for entry in entries:
        metadata = entry.absolute.lstat()
        if (
            stat.S_ISDIR(metadata.st_mode) != entry.is_directory
            or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode))
            or _managed_state(metadata) != entry.state
        ):
            raise BackupError("managed backup path changed during archive creation")


def _require_stable_directory_identity(
    reference: os.stat_result,
    *observed: os.stat_result,
) -> None:
    identity = _managed_identity(reference)
    if not stat.S_ISDIR(reference.st_mode) or any(
        not stat.S_ISDIR(metadata.st_mode) or _managed_identity(metadata) != identity
        for metadata in observed
    ):
        raise BackupError("managed backup path contains a symlink or changed directory")


def _managed_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_mode, metadata.st_dev, metadata.st_ino)


def _managed_state(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _archive_info(
    relative: str,
    *,
    is_directory: bool = False,
    payload_prefix: bool = True,
) -> zipfile.ZipInfo:
    name = f"{PAYLOAD_PREFIX}{relative}" if payload_prefix else relative
    if is_directory:
        name = f"{name}/"
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = ((stat.S_IFDIR | 0o700) if is_directory else (stat.S_IFREG | 0o600)) << 16
    info.compress_type = zipfile.ZIP_STORED if is_directory else zipfile.ZIP_DEFLATED
    return info


def _require_output_parent_stable(
    output_path: Path,
    descriptor: int,
    identity: tuple[int, int, int],
    *,
    resolved_output: Path,
    workspace_root: Path,
) -> None:
    try:
        descriptor_state = os.fstat(descriptor)
        path_state = output_path.parent.lstat()
        current_output = output_path.resolve(strict=False)
    except OSError as exc:
        raise BackupError("backup output parent changed during creation") from exc
    if (
        not stat.S_ISDIR(descriptor_state.st_mode)
        or not stat.S_ISDIR(path_state.st_mode)
        or _managed_identity(descriptor_state) != identity
        or _managed_identity(path_state) != identity
        or current_output != resolved_output
        or current_output == workspace_root
        or current_output.is_relative_to(workspace_root)
    ):
        raise BackupError("backup output parent changed during creation")


def _sync_directory_descriptor(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        unsupported = {
            errno.EINVAL,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if exc.errno not in unsupported:
            raise


def _unlink_owned_entry(
    path: str | Path,
    identity: tuple[int, int],
    *,
    dir_fd: int | None = None,
) -> bool:
    try:
        metadata = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if (metadata.st_dev, metadata.st_ino) != identity:
            return False
        os.unlink(path, dir_fd=dir_fd)
        return True
    except OSError:
        return False


def verify_backup_archive(path: Path) -> VerifiedBackup:
    candidate = path.expanduser().absolute()
    try:
        path_before = candidate.lstat()
    except OSError as exc:
        raise BackupVerificationError("backup archive must be a regular file") from exc
    if not stat.S_ISREG(path_before.st_mode):
        raise BackupVerificationError("backup archive must be a regular file")
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(candidate, flags)
        descriptor_before = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_before.st_mode):
            raise BackupVerificationError("backup archive must be a regular file")
        path_after_open = candidate.lstat()
        _require_unchanged_archive(descriptor_before, path_before, path_after_open)
        source = os.fdopen(descriptor, "rb")
        descriptor = None
        with source:
            archive_path = candidate.resolve(strict=True)
            path_after_resolve = candidate.lstat()
            resolved_after_open = archive_path.lstat()
            _require_unchanged_archive(
                descriptor_before,
                path_after_resolve,
                resolved_after_open,
            )
            _preflight_archive(source)
            archive_sha256 = _file_sha256(source)
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                _validate_member_metadata(infos)
                names = [info.filename for info in infos]
                if len(names) != len(set(names)):
                    raise BackupVerificationError("backup contains duplicate ZIP members")
                if names.count(MANIFEST_NAME) != 1:
                    raise BackupVerificationError("backup must contain exactly one manifest")
                info_by_name = {info.filename: info for info in infos}
                manifest_info = info_by_name[MANIFEST_NAME]
                manifest_content = _read_member(archive, manifest_info, MAX_MANIFEST_BYTES)
                try:
                    manifest = BackupManifest.model_validate_json(manifest_content, strict=True)
                except ValidationError as exc:
                    raise BackupVerificationError("backup manifest is invalid") from exc
                if manifest_info.is_dir():
                    raise BackupVerificationError("backup manifest must be a regular file")
                expected_names = {MANIFEST_NAME}
                expected_names.update(f"{PAYLOAD_PREFIX}{path}/" for path in manifest.directories)
                expected_names.update(f"{PAYLOAD_PREFIX}{record.path}" for record in manifest.files)
                if set(names) != expected_names:
                    raise BackupVerificationError("backup members do not match its manifest")
                if any(
                    not info_by_name[f"{PAYLOAD_PREFIX}{path}/"].is_dir()
                    for path in manifest.directories
                ):
                    raise BackupVerificationError("backup directory member has the wrong type")
                if any(
                    info_by_name[f"{PAYLOAD_PREFIX}{record.path}"].is_dir()
                    for record in manifest.files
                ):
                    raise BackupVerificationError("backup file member has the wrong type")
                records = {record.path: record for record in manifest.files}
                config_record = records.get(CONFIG_FILENAME)
                if config_record is None:
                    raise BackupVerificationError("backup does not contain bundlewalker.toml")
                if config_record.size > MAX_WORKSPACE_CONFIG_BYTES:
                    raise BackupVerificationError("backup workspace configuration is too large")
                config_content: bytes | None = None
                for record in manifest.files:
                    member = info_by_name[f"{PAYLOAD_PREFIX}{record.path}"]
                    content = _verify_member(
                        archive,
                        member,
                        record,
                        capture=record.path == CONFIG_FILENAME,
                    )
                    if content is not None:
                        config_content = content
                if config_content is None:
                    raise BackupVerificationError("backup workspace configuration is unavailable")
                try:
                    config = parse_workspace_config(
                        config_content.decode("utf-8", errors="strict"),
                        source=f"{archive_path}:{CONFIG_FILENAME}",
                    )
                except (BundleWalkerError, UnicodeDecodeError) as exc:
                    raise BackupVerificationError(
                        "backup workspace configuration is invalid"
                    ) from exc
                _validate_managed_payload(manifest, config)
            descriptor_after = os.fstat(source.fileno())
            final_path_before_resolve = candidate.lstat()
            final_archive_path = candidate.resolve(strict=True)
            final_path_after_resolve = candidate.lstat()
            resolved_final = final_archive_path.lstat()
            if final_archive_path != archive_path:
                raise BackupVerificationError("backup archive changed while it was verified")
            _require_unchanged_archive(
                descriptor_before,
                descriptor_after,
                final_path_before_resolve,
                final_path_after_resolve,
                resolved_final,
            )
            return VerifiedBackup(archive_path, archive_sha256, manifest)
    except zipfile.BadZipFile as exc:
        raise BackupVerificationError("backup archive is not a valid ZIP") from exc
    except (NotImplementedError, RuntimeError, UnicodeDecodeError, zlib.error) as exc:
        raise BackupVerificationError("backup archive uses an unsupported ZIP feature") from exc
    except OSError as exc:
        raise BackupVerificationError("backup archive could not be read") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _canonical_relative_path(value: str) -> str:
    if (
        not value
        or len(value) > MAX_BACKUP_PATH_CHARACTERS
        or "\\" in value
        or "\x00" in value
        or value.endswith("/")
    ):
        raise ValueError("backup path is unsafe")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(
            len(part) >= 2 and part[0].isascii() and part[0].isalpha() and part[1] == ":"
            for part in path.parts
        )
        or path.as_posix() != value
    ):
        raise ValueError("backup path is unsafe")
    return value


def _validate_member_metadata(infos: list[zipfile.ZipInfo]) -> None:
    if len(infos) - 1 > MAX_BACKUP_ENTRIES:
        raise BackupVerificationError("backup contains too many entries")
    for info in infos:
        if info.flag_bits & 0x1:
            raise BackupVerificationError("encrypted backup members are unsupported")
        if info.flag_bits & ~_SUPPORTED_ZIP_FLAGS:
            raise BackupVerificationError("backup contains unsupported ZIP flags")
        if info.compress_type != zipfile.ZIP_DEFLATED and not (
            info.is_dir() and info.compress_type == zipfile.ZIP_STORED
        ):
            raise BackupVerificationError("backup contains unsupported compression")
        if info.orig_filename != info.filename:
            raise BackupVerificationError("backup contains an unsafe member path")
        if info.filename != MANIFEST_NAME:
            raw_name = info.filename.removeprefix(PAYLOAD_PREFIX).removesuffix("/")
            try:
                _canonical_relative_path(raw_name)
            except ValueError as exc:
                raise BackupVerificationError("backup contains an unsafe member path") from exc
            if not info.filename.startswith(PAYLOAD_PREFIX):
                raise BackupVerificationError("backup contains a member outside workspace/")
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BackupVerificationError("backup contains a symlink or special file")
        if file_type and stat.S_ISDIR(mode) != info.is_dir():
            raise BackupVerificationError("backup member name and type disagree")
        if info.is_dir() and info.file_size != 0:
            raise BackupVerificationError("backup directory member contains data")


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limit: int,
) -> bytes:
    if info.file_size > limit:
        raise BackupVerificationError("backup member exceeds its supported size")
    with archive.open(info) as member:
        content = member.read(limit + 1)
        if len(content) > limit or member.read(1):
            raise BackupVerificationError("backup member exceeds its declared size")
    return content


def _verify_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    record: BackupFileRecord,
    *,
    capture: bool,
) -> bytes | None:
    if info.file_size != record.size:
        raise BackupVerificationError(f"backup size mismatch: {record.path}")
    digest = hashlib.sha256()
    count = 0
    captured = bytearray() if capture else None
    with archive.open(info) as member:
        while chunk := member.read(1024 * 1024):
            count += len(chunk)
            if count > record.size:
                raise BackupVerificationError(f"backup size mismatch: {record.path}")
            digest.update(chunk)
            if captured is not None:
                captured.extend(chunk)
    if count != record.size:
        raise BackupVerificationError(f"backup size mismatch: {record.path}")
    if digest.hexdigest() != record.sha256:
        raise BackupVerificationError(f"backup digest mismatch: {record.path}")
    return bytes(captured) if captured is not None else None


def _validate_managed_payload(manifest: BackupManifest, config: WorkspaceConfig) -> None:
    files = {record.path for record in manifest.files}
    directories = set(manifest.directories)
    required_files = {CONFIG_FILENAME, config.conventions_file}
    required_directories = {config.raw_dir, config.wiki_dir}
    if not required_files <= files or not required_directories <= directories:
        raise BackupVerificationError("backup is missing a configured managed path")
    reserved = PurePosixPath(".bundlewalker")
    managed_roots = (
        PurePosixPath(config.conventions_file),
        PurePosixPath(config.raw_dir),
        PurePosixPath(config.wiki_dir),
    )
    reserved_key = _portable_path_component(reserved.name)
    if any(
        root.parts and _portable_path_component(root.parts[0]) == reserved_key
        for root in managed_roots
    ):
        raise BackupVerificationError("backup configuration overlaps reserved internal state")
    for value in files:
        path = PurePosixPath(value)
        if path == PurePosixPath(CONFIG_FILENAME) or path == managed_roots[0]:
            continue
        if not any(root in path.parents for root in managed_roots[1:]):
            raise BackupVerificationError("backup contains an unmanaged file")
    for value in directories:
        path = PurePosixPath(value)
        if not any(
            path == root or root in path.parents or path in root.parents for root in managed_roots
        ):
            raise BackupVerificationError("backup contains an unmanaged directory")


def _require_unchanged_archive(
    reference: os.stat_result,
    *observed: os.stat_result,
) -> None:
    reference_state = _archive_state(reference)
    if any(
        not stat.S_ISREG(metadata.st_mode) or _archive_state(metadata) != reference_state
        for metadata in observed
    ):
        raise BackupVerificationError("backup archive changed while it was verified")


def _archive_state(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _file_sha256(source: IO[bytes]) -> str:
    digest = hashlib.sha256()
    source.seek(0)
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _portable_path_component(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _preflight_archive(source: IO[bytes]) -> None:
    source.seek(0, 2)
    archive_size = source.tell()
    if archive_size < _EOCD_SIZE:
        raise BackupVerificationError("backup archive is not a valid ZIP")
    tail_size = min(archive_size, _EOCD_SIZE + _MAX_ZIP_COMMENT_BYTES)
    source.seek(archive_size - tail_size)
    tail = _read_exact(source, tail_size)
    eocd_position = _find_eocd(tail)
    eocd_offset = archive_size - tail_size + eocd_position
    (
        _,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
        _,
    ) = struct.unpack_from("<4sHHHHIIH", tail, eocd_position)
    directory_end = eocd_offset
    if (
        directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
        or _has_zip64_locator(source, eocd_offset)
    ):
        (
            disk_entries,
            total_entries,
            directory_size,
            directory_offset,
            directory_end,
        ) = _read_zip64_directory_metadata(source, eocd_offset)
    elif disk_number != 0 or directory_disk != 0 or disk_entries != total_entries:
        raise BackupVerificationError("multi-disk backup archives are unsupported")
    _preflight_central_directory(
        source,
        directory_offset=directory_offset,
        directory_size=directory_size,
        directory_end=directory_end,
        declared_entries=total_entries,
    )


def _find_eocd(tail: bytes) -> int:
    search_end = len(tail)
    while True:
        position = tail.rfind(_EOCD_SIGNATURE, 0, search_end)
        if position < 0:
            raise BackupVerificationError("backup archive is not a valid ZIP")
        if position + _EOCD_SIZE <= len(tail):
            comment_size = struct.unpack_from("<H", tail, position + 20)[0]
            if position + _EOCD_SIZE + comment_size == len(tail):
                return position
        search_end = position


def _has_zip64_locator(source: IO[bytes], eocd_offset: int) -> bool:
    locator_offset = eocd_offset - _ZIP64_LOCATOR_SIZE
    if locator_offset < 0:
        return False
    source.seek(locator_offset)
    return source.read(len(_ZIP64_LOCATOR_SIGNATURE)) == _ZIP64_LOCATOR_SIGNATURE


def _read_zip64_directory_metadata(
    source: IO[bytes],
    eocd_offset: int,
) -> tuple[int, int, int, int, int]:
    locator_offset = eocd_offset - _ZIP64_LOCATOR_SIZE
    if locator_offset < 0:
        raise BackupVerificationError("backup ZIP64 metadata is invalid")
    source.seek(locator_offset)
    locator = _read_exact(source, _ZIP64_LOCATOR_SIZE)
    signature, directory_disk, zip64_offset, disk_count = struct.unpack(
        "<4sIQI",
        locator,
    )
    if signature != _ZIP64_LOCATOR_SIGNATURE or directory_disk != 0 or disk_count != 1:
        raise BackupVerificationError("backup ZIP64 metadata is invalid")
    source.seek(zip64_offset)
    record = _read_exact(source, _ZIP64_EOCD_SIZE)
    (
        signature,
        record_size,
        _,
        _,
        disk_number,
        central_directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
    ) = struct.unpack("<4sQHHIIQQQQ", record)
    if (
        signature != _ZIP64_EOCD_SIGNATURE
        or record_size != 44
        or disk_number != 0
        or central_directory_disk != 0
        or disk_entries != total_entries
        or zip64_offset + _ZIP64_EOCD_SIZE != locator_offset
    ):
        raise BackupVerificationError("backup ZIP64 metadata is invalid")
    return disk_entries, total_entries, directory_size, directory_offset, zip64_offset


def _preflight_central_directory(
    source: IO[bytes],
    *,
    directory_offset: int,
    directory_size: int,
    directory_end: int,
    declared_entries: int,
) -> None:
    if declared_entries - 1 > MAX_BACKUP_ENTRIES:
        raise BackupVerificationError("backup contains too many entries")
    if directory_size > _MAX_CENTRAL_DIRECTORY_BYTES:
        raise BackupVerificationError("backup central directory is too large")
    if directory_offset + directory_size != directory_end:
        raise BackupVerificationError("backup central directory is invalid")
    source.seek(directory_offset)
    remaining = directory_size
    actual_entries = 0
    while remaining:
        if remaining < _CENTRAL_DIRECTORY_HEADER_SIZE:
            raise BackupVerificationError("backup central directory is invalid")
        header = _read_exact(source, _CENTRAL_DIRECTORY_HEADER_SIZE)
        if header[:4] != _CENTRAL_DIRECTORY_SIGNATURE:
            raise BackupVerificationError("backup central directory is invalid")
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
        disk_number = struct.unpack_from("<H", header, 34)[0]
        variable_size = name_size + extra_size + comment_size
        record_size = _CENTRAL_DIRECTORY_HEADER_SIZE + variable_size
        if disk_number != 0 or record_size > remaining:
            raise BackupVerificationError("backup central directory is invalid")
        source.seek(variable_size, 1)
        remaining -= record_size
        actual_entries += 1
        if actual_entries - 1 > MAX_BACKUP_ENTRIES:
            raise BackupVerificationError("backup contains too many entries")
    if actual_entries != declared_entries:
        raise BackupVerificationError("backup central directory entry count is invalid")


def _read_exact(source: IO[bytes], size: int) -> bytes:
    content = source.read(size)
    if len(content) != size:
        raise BackupVerificationError("backup archive is truncated")
    return content
