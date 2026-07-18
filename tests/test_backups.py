# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import struct
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Literal, cast

import pytest

import bundlewalker.backups as backups_module
from bundlewalker.backups import (
    ARCHIVE_FORMAT,
    ARCHIVE_SCHEMA_VERSION,
    MANIFEST_NAME,
    MAX_BACKUP_ENTRIES,
    MAX_MANIFEST_BYTES,
    BackupManifest,
    VerifiedBackup,
    verify_backup_archive,
)
from bundlewalker.errors import BackupVerificationError
from bundlewalker.workspace import DEFAULT_CONFIG_TEXT, MAX_WORKSPACE_CONFIG_BYTES

CREATED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _valid_payload() -> dict[str, bytes]:
    return {
        "bundlewalker.toml": DEFAULT_CONFIG_TEXT.encode(),
        "conventions.md": b"# Conventions\n",
        "wiki/index.md": b"# Index\n",
        "wiki/log.md": b"# Log\n",
        "wiki/sources/index.md": b"# Sources\n",
        "wiki/topics/index.md": b"# Topics\n",
        "wiki/entities/index.md": b"# Entities\n",
        "wiki/syntheses/index.md": b"# Syntheses\n",
    }


def _write_archive(
    path: Path,
    *,
    payload: dict[str, bytes] | None = None,
    manifest_updates: dict[str, object] | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> None:
    files = payload or _valid_payload()
    directories = sorted(
        {
            "raw",
            "wiki",
            "wiki/sources",
            "wiki/topics",
            "wiki/entities",
            "wiki/syntheses",
        }
    )
    manifest: dict[str, object] = {
        "archive_format": ARCHIVE_FORMAT,
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "created_at": CREATED_AT.isoformat(),
        "bundlewalker_version": "0.4.0a1",
        "workspace_format_version": 1,
        "directories": directories,
        "files": [
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in sorted(files.items())
        ],
    }
    manifest.update(manifest_updates or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr(
            "bundlewalker-backup.json",
            json.dumps(manifest, sort_keys=True).encode(),
        )
        for directory in directories:
            archive.writestr(f"workspace/{directory}/", b"")
        for name, content in sorted(files.items()):
            archive.writestr(f"workspace/{name}", content)
        for name, content in extra_members:
            archive.writestr(name, content)


def _file_records(payload: dict[str, bytes] | None = None) -> list[dict[str, object]]:
    return [
        {
            "path": name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for name, content in sorted((payload or _valid_payload()).items())
    ]


def _patch_member_info(
    monkeypatch: pytest.MonkeyPatch,
    member_name: str,
    update: Callable[[zipfile.ZipInfo], None],
) -> None:
    original_infolist = zipfile.ZipFile.infolist

    def patched_infolist(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        infos = original_infolist(archive)
        update(next(info for info in infos if info.filename == member_name))
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", patched_infolist)


def _patch_member_stream(
    monkeypatch: pytest.MonkeyPatch,
    member_name: str,
    content: bytes,
) -> None:
    original_open = zipfile.ZipFile.open

    def patched_open(
        archive: zipfile.ZipFile,
        name: str | zipfile.ZipInfo,
        mode: Literal["r"] = "r",
        pwd: bytes | None = None,
        *,
        force_zip64: bool = False,
    ) -> IO[bytes]:
        filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if filename == member_name:
            return io.BytesIO(content)
        return original_open(
            archive,
            name,
            mode,
            pwd,
            force_zip64=force_zip64,
        )

    monkeypatch.setattr(zipfile.ZipFile, "open", patched_open)


def _rewrite_member_mode(path: Path, member_name: str, mode: int) -> None:
    replacement = path.with_name("replacement.zip")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename == member_name:
                info.create_system = 3
                info.external_attr = mode << 16
            target.writestr(info, content)
    os.replace(replacement, path)


def _remove_member(path: Path, member_name: str) -> None:
    replacement = path.with_name("replacement.zip")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            if info.filename != member_name:
                target.writestr(info, source.read(info))
    os.replace(replacement, path)


def _rewrite_member_content(path: Path, member_name: str, content: bytes) -> None:
    replacement = path.with_name("replacement.zip")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            target.writestr(info, content if info.filename == member_name else source.read(info))
    os.replace(replacement, path)


def _rewrite_member_compression(path: Path, member_name: str, compression: int) -> None:
    replacement = path.with_name("replacement.zip")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename == member_name:
                info.compress_type = compression
            target.writestr(info, content)
    os.replace(replacement, path)


def _corrupt_compressed_member(path: Path, member_name: str) -> None:
    archive_bytes = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(member_name)
    header_offset = info.header_offset
    name_size, extra_size = struct.unpack_from("<HH", archive_bytes, header_offset + 26)
    content_offset = header_offset + 30 + name_size + extra_size
    archive_bytes[content_offset : content_offset + info.compress_size] = (
        b"\xff" * info.compress_size
    )
    path.write_bytes(archive_bytes)


def test_verify_accepts_exact_current_archive(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    _write_archive(archive)

    verified = verify_backup_archive(archive)

    assert isinstance(verified, VerifiedBackup)
    assert isinstance(verified.manifest, BackupManifest)
    assert verified.archive_path == archive.resolve()
    assert verified.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert verified.manifest.workspace_format_version == 1
    assert verified.file_count == len(_valid_payload())
    assert verified.byte_count == sum(map(len, _valid_payload().values()))


def test_verify_accepts_stored_empty_directory_member(tmp_path: Path) -> None:
    archive = tmp_path / "stored-directory.zip"
    _write_archive(archive)
    _rewrite_member_compression(archive, "workspace/raw/", zipfile.ZIP_STORED)

    verified = verify_backup_archive(archive)

    assert verified.file_count == len(_valid_payload())


@pytest.mark.parametrize(
    "updates",
    [
        {"archive_format": "other"},
        {"schema_version": 2},
        {"workspace_format_version": 2},
        {"unknown": True},
        {"directories": ["wiki", "wiki"]},
    ],
)
def test_verify_rejects_invalid_manifest(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    archive = tmp_path / "invalid.zip"
    _write_archive(archive, manifest_updates=updates)

    with pytest.raises(BackupVerificationError, match="manifest"):
        verify_backup_archive(archive)


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "workspace/../escape",
        "workspace\\escape",
        "C:/escape",
        "workspace//double",
    ],
)
def test_verify_rejects_unsafe_or_unexpected_member(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.zip"
    _write_archive(archive, extra_members=((name, b"unsafe"),))

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)


def test_verify_rejects_duplicate_zip_member(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_archive(
            archive,
            extra_members=(("workspace/wiki/index.md", b"duplicate"),),
        )

    with pytest.raises(BackupVerificationError, match="duplicate"):
        verify_backup_archive(archive)


def test_verify_rejects_digest_and_size_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "changed.zip"
    manifest_files = [
        {
            "path": name,
            "size": len(content),
            "sha256": (
                "0" * 64 if name == "wiki/index.md" else hashlib.sha256(content).hexdigest()
            ),
        }
        for name, content in sorted(_valid_payload().items())
    ]
    _write_archive(archive, manifest_updates={"files": manifest_files})

    with pytest.raises(BackupVerificationError, match="digest"):
        verify_backup_archive(archive)


def test_verify_rejects_symlink_attributes(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    _write_archive(archive)
    replacement = tmp_path / "replacement.zip"
    with (
        zipfile.ZipFile(archive) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "workspace/wiki/index.md":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target.writestr(info, content)
    os.replace(replacement, archive)

    with pytest.raises(BackupVerificationError, match=r"symlink|special"):
        verify_backup_archive(archive)


def test_verify_rejects_missing_manifest_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "missing-manifest.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("workspace/wiki/", b"")

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_duplicate_manifest_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate-manifest.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_archive(
            archive,
            extra_members=((MANIFEST_NAME, b"{}"),),
        )

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize(
    "member_name",
    [MANIFEST_NAME, "workspace/wiki/index.md"],
)
def test_verify_rejects_encrypted_member_flag_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_name: str,
) -> None:
    archive = tmp_path / "encrypted.zip"
    _write_archive(archive)

    def mark_encrypted(info: zipfile.ZipInfo) -> None:
        info.flag_bits |= 0x1

    _patch_member_info(monkeypatch, member_name, mark_encrypted)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_special_file_mode_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "special.zip"
    _write_archive(archive)
    _rewrite_member_mode(
        archive,
        "workspace/wiki/index.md",
        stat.S_IFIFO | 0o600,
    )

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize("unsafe_path", ["wiki/\x00index.md", "wiki/./index.md"])
def test_verify_rejects_nul_and_dot_segments_without_extracting(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    archive = tmp_path / "unsafe-manifest-path.zip"
    records = _file_records()
    for record in records:
        if record["path"] == "wiki/index.md":
            record["path"] = unsafe_path
    records.sort(key=lambda record: str(record["path"]))
    _write_archive(archive, manifest_updates={"files": records})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_unsorted_manifest_directories_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsorted-directories.zip"
    _write_archive(archive, manifest_updates={"directories": ["wiki", "raw"]})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_unsorted_manifest_files_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "unsorted-files.zip"
    _write_archive(archive, manifest_updates={"files": list(reversed(_file_records()))})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_overlapping_manifest_paths_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "overlapping-paths.zip"
    records = _file_records()
    records.append(
        {
            "path": "wiki",
            "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    )
    records.sort(key=lambda record: str(record["path"]))
    _write_archive(
        archive,
        manifest_updates={
            "directories": [
                "raw",
                "wiki/entities",
                "wiki/sources",
                "wiki/syntheses",
                "wiki/topics",
            ],
            "files": records,
        },
    )

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_manifest_larger_than_limit_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "oversized-manifest.zip"
    _write_archive(archive)

    def report_oversized_manifest(info: zipfile.ZipInfo) -> None:
        info.file_size = MAX_MANIFEST_BYTES + 1

    _patch_member_info(monkeypatch, MANIFEST_NAME, report_oversized_manifest)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_more_than_entry_limit_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "too-many-entries.zip"
    _write_archive(archive)
    original_infolist = zipfile.ZipFile.infolist

    class ReportedOversizedInfoList(list[zipfile.ZipInfo]):
        def __len__(self) -> int:
            return MAX_BACKUP_ENTRIES + 2

    def oversized_infolist(source: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        return ReportedOversizedInfoList(original_infolist(source))

    monkeypatch.setattr(zipfile.ZipFile, "infolist", oversized_infolist)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_path_larger_than_limit_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "oversized-path.zip"
    records = _file_records()
    records.append(
        {
            "path": "a" * 4_097,
            "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    )
    records.sort(key=lambda record: str(record["path"]))
    _write_archive(archive, manifest_updates={"files": records})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_missing_configured_roots_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "missing-configured-root.zip"
    payload = _valid_payload()
    payload["bundlewalker.toml"] = DEFAULT_CONFIG_TEXT.replace(
        'raw_dir = "raw"',
        'raw_dir = "incoming"',
    ).encode()
    _write_archive(archive, payload=payload)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_configuration_larger_than_limit_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "oversized-config.zip"
    records = _file_records()
    for record in records:
        if record["path"] == "bundlewalker.toml":
            record["size"] = MAX_WORKSPACE_CONFIG_BYTES + 1
    _write_archive(archive, manifest_updates={"files": records})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize("delta", [-1, 1])
def test_verify_rejects_declared_size_different_from_stream_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delta: int,
) -> None:
    archive = tmp_path / "forged-stream-size.zip"
    _write_archive(archive)
    original = _valid_payload()["conventions.md"]
    forged = original[:-1] if delta < 0 else original + b"x"
    _patch_member_stream(monkeypatch, "workspace/conventions.md", forged)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_sha_mismatch_when_zip_crc_is_valid_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "sha-mismatch.zip"
    records = _file_records()
    for record in records:
        if record["path"] == "wiki/index.md":
            record["sha256"] = "0" * 64
    _write_archive(archive, manifest_updates={"files": records})
    with zipfile.ZipFile(archive) as source:
        assert source.testzip() is None

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_future_workspace_format_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "future-workspace.zip"
    _write_archive(archive, manifest_updates={"workspace_format_version": 2})

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_safe_extra_member_not_in_manifest_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "extra-member.zip"
    _write_archive(
        archive,
        extra_members=(("workspace/wiki/extra.md", b"# Extra\n"),),
    )

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_manifest_member_missing_from_zip_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "missing-member.zip"
    _write_archive(archive)
    _remove_member(archive, "workspace/wiki/log.md")

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize(
    ("member_name", "forged_mode"),
    [
        (MANIFEST_NAME, stat.S_IFDIR | 0o700),
        ("workspace/raw/", stat.S_IFREG | 0o600),
        ("workspace/wiki/index.md", stat.S_IFDIR | 0o700),
    ],
)
def test_verify_rejects_member_name_and_mode_type_disagreement_without_extracting(
    tmp_path: Path,
    member_name: str,
    forged_mode: int,
) -> None:
    archive = tmp_path / "wrong-member-type.zip"
    _write_archive(archive)
    _rewrite_member_mode(archive, member_name, forged_mode)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_manifest_ancestor_validation_is_linear_in_entry_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_posix_path = PurePosixPath

    def bounded_posix_path(value: str) -> PurePosixPath:
        nonlocal calls
        calls += 1
        if calls > 5_000:
            raise AssertionError("manifest path validation exceeded its linear work budget")
        return real_posix_path(value)

    monkeypatch.setattr(backups_module, "PurePosixPath", bounded_posix_path)
    records = tuple(
        {
            "path": f"raw/{index:04}.txt",
            "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
        for index in range(1_000)
    )

    manifest = BackupManifest.model_validate(
        {
            "archive_format": ARCHIVE_FORMAT,
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "created_at": CREATED_AT,
            "bundlewalker_version": "0.4.0a1",
            "workspace_format_version": 1,
            "directories": ("raw", "wiki"),
            "files": records,
        },
        strict=True,
    )

    assert len(manifest.files) == 1_000
    assert calls <= 5_000


def test_verify_rejects_unsupported_compression_as_typed_error_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "unsupported-compression.zip"
    _write_archive(archive)

    def report_unsupported_compression(info: zipfile.ZipInfo) -> None:
        info.compress_type = 99

    _patch_member_info(
        monkeypatch,
        "workspace/wiki/index.md",
        report_unsupported_compression,
    )

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize("flag", [0x20, 0x40])
def test_verify_rejects_unsupported_zip_flags_as_typed_error_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: int,
) -> None:
    archive = tmp_path / "unsupported-flag.zip"
    _write_archive(archive)

    def report_unsupported_flag(info: zipfile.ZipInfo) -> None:
        info.flag_bits |= flag

    _patch_member_info(monkeypatch, "workspace/wiki/index.md", report_unsupported_flag)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_raw_member_nul_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "raw-nul.zip"
    payload = _valid_payload()
    content = payload.pop("wiki/index.md")
    payload["wiki/index.mdX"] = content
    records = _file_records(payload)
    for record in records:
        if record["path"] == "wiki/index.mdX":
            record["path"] = "wiki/index.md"
    records.sort(key=lambda record: str(record["path"]))
    _write_archive(archive, payload=payload, manifest_updates={"files": records})
    unsafe_name = b"workspace/wiki/index.mdX"
    nul_name = b"workspace/wiki/index.md\x00"
    archive_bytes = archive.read_bytes()
    assert archive_bytes.count(unsafe_name) == 2
    archive.write_bytes(archive_bytes.replace(unsafe_name, nul_name))

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize(
    "reserved_variant",
    [
        ".BundleWalker",
        "\uff0e\uff22\uff55\uff4e\uff44\uff4c\uff45\uff37\uff41\uff4c\uff4b\uff45\uff52",
    ],
)
def test_verify_rejects_portable_reserved_managed_root_collision_without_extracting(
    tmp_path: Path,
    reserved_variant: str,
) -> None:
    archive = tmp_path / "reserved-case-variant.zip"
    payload = _valid_payload()
    content = payload.pop("conventions.md")
    conventions_path = f"{reserved_variant}/conventions.md"
    payload[conventions_path] = content
    payload["bundlewalker.toml"] = DEFAULT_CONFIG_TEXT.replace(
        'conventions_file = "conventions.md"',
        f'conventions_file = "{conventions_path}"',
    ).encode()
    _write_archive(archive, payload=payload)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_nonempty_directory_member_without_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "nonempty-directory.zip"
    _write_archive(archive)
    _rewrite_member_content(archive, "workspace/raw/", b"unexpected")

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_preflights_zip64_entry_count_before_zipfile_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "zip64-too-many.zip"
    entry_count = MAX_BACKUP_ENTRIES + 2
    zip64_eocd = struct.pack(
        "<4sQHHIIQQQQ",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        entry_count,
        entry_count,
        0,
        0,
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, 0, 1)
    eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0,
        0,
        0xFFFF,
        0xFFFF,
        0xFFFFFFFF,
        0xFFFFFFFF,
        0,
    )
    archive.write_bytes(zip64_eocd + locator + eocd)

    def unexpected_zipfile(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile must not see an over-limit central directory")

    monkeypatch.setattr(zipfile, "ZipFile", unexpected_zipfile)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_preflights_central_directory_size_before_zipfile_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "central-directory-too-large.zip"
    excessive_size = MAX_MANIFEST_BYTES + MAX_BACKUP_ENTRIES * 128 + 1
    archive.write_bytes(
        struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0,
            0,
            0,
            0,
            excessive_size,
            0,
            0,
        )
    )

    def unexpected_zipfile(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile must not see an oversized central directory")

    monkeypatch.setattr(zipfile, "ZipFile", unexpected_zipfile)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_treats_exact_classic_entry_sentinel_as_literal_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "classic-max-count.zip"
    archive.write_bytes(
        struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0,
            0,
            0xFFFF,
            0xFFFF,
            0,
            0,
            0,
        )
    )
    observed_counts: list[int] = []

    def capture_preflight(
        source: IO[bytes],
        *,
        directory_offset: int,
        directory_size: int,
        directory_end: int,
        declared_entries: int,
    ) -> None:
        del source, directory_offset, directory_size, directory_end
        observed_counts.append(declared_entries)

    class ReachedZipFile(Exception):
        pass

    def reached_zipfile(*args: object, **kwargs: object) -> None:
        raise ReachedZipFile

    monkeypatch.setattr(backups_module, "_preflight_central_directory", capture_preflight)
    monkeypatch.setattr(zipfile, "ZipFile", reached_zipfile)

    with pytest.raises(ReachedZipFile):
        verify_backup_archive(archive)
    assert observed_counts == [0xFFFF]
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_wraps_corrupt_deflate_stream_as_typed_error_without_extracting(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "corrupt-deflate.zip"
    _write_archive(archive)
    _corrupt_compressed_member(archive, "workspace/conventions.md")

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)
    assert list(tmp_path.iterdir()) == [archive]


def test_verify_rejects_path_replacement_between_hash_and_manifest_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "replaced.zip"
    replacement = tmp_path / "replacement.zip"
    _write_archive(archive)
    _write_archive(
        replacement,
        manifest_updates={"bundlewalker_version": "replacement-archive"},
    )
    original_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    original_file_sha256 = cast(
        Callable[[IO[bytes]], str],
        vars(backups_module)["_file_sha256"],
    )

    def replace_after_hash(source: IO[bytes]) -> str:
        digest = original_file_sha256(source)
        assert digest == original_digest
        os.replace(replacement, archive)
        return digest

    monkeypatch.setattr(backups_module, "_file_sha256", replace_after_hash)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)


def test_verify_rejects_symlink_swap_between_hash_and_manifest_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "symlink-swapped.zip"
    moved = tmp_path / "moved.zip"
    _write_archive(archive)
    original_file_sha256 = cast(
        Callable[[IO[bytes]], str],
        vars(backups_module)["_file_sha256"],
    )

    def symlink_after_hash(source: IO[bytes]) -> str:
        digest = original_file_sha256(source)
        archive.rename(moved)
        archive.symlink_to(moved.name)
        return digest

    monkeypatch.setattr(backups_module, "_file_sha256", symlink_after_hash)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)


def test_verify_rejects_in_place_mutation_between_hash_and_manifest_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "mutated.zip"
    _write_archive(archive)
    original_file_sha256 = cast(
        Callable[[IO[bytes]], str],
        vars(backups_module)["_file_sha256"],
    )

    def append_after_hash(source: IO[bytes]) -> str:
        digest = original_file_sha256(source)
        with archive.open("ab") as destination:
            destination.write(b"trailing mutation")
        return digest

    monkeypatch.setattr(backups_module, "_file_sha256", append_after_hash)

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)


@pytest.mark.parametrize("unsafe_path", ["C:escape", "raw/C:escape"])
def test_verify_rejects_drive_relative_manifest_path(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    archive = tmp_path / "drive-relative-manifest.zip"
    records = _file_records()
    for record in records:
        if record["path"] == "wiki/index.md":
            record["path"] = unsafe_path
    records.sort(key=lambda record: str(record["path"]))
    _write_archive(archive, manifest_updates={"files": records})

    with pytest.raises(BackupVerificationError, match="manifest"):
        verify_backup_archive(archive)


@pytest.mark.parametrize(
    "unsafe_name",
    ["workspace/C:escape", "workspace/raw/C:escape"],
)
def test_verify_rejects_drive_relative_raw_member_name(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    archive = tmp_path / "drive-relative-member.zip"
    _write_archive(archive, extra_members=((unsafe_name, b"unsafe"),))

    with pytest.raises(BackupVerificationError, match="unsafe member path"):
        verify_backup_archive(archive)


def test_verify_rejects_non_utc_manifest_timestamp(tmp_path: Path) -> None:
    archive = tmp_path / "non-utc-timestamp.zip"
    _write_archive(
        archive,
        manifest_updates={"created_at": "2026-07-18T14:00:00+02:00"},
    )

    with pytest.raises(BackupVerificationError, match="manifest"):
        verify_backup_archive(archive)
