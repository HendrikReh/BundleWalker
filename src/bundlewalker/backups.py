# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import os
import stat
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import IO, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bundlewalker.compatibility import CURRENT_WORKSPACE_FORMAT
from bundlewalker.errors import BackupVerificationError, BundleWalkerError
from bundlewalker.workspace import (
    CONFIG_FILENAME,
    MAX_WORKSPACE_CONFIG_BYTES,
    WorkspaceConfig,
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
