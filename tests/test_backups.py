# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import struct
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import IO, Any, Literal, cast

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
    create_quiescent_backup,
    create_workspace_backup,
    verify_backup_archive,
)
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
from bundlewalker.errors import BackupError, BackupVerificationError, ReviewPendingError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    ReviewStatus,
    discard_pending_review,
    get_pending_review,
    prepare_transaction,
    quiescent_workspace,
)
from bundlewalker.workspace import (
    DEFAULT_CONFIG_TEXT,
    MAX_WORKSPACE_CONFIG_BYTES,
    Workspace,
    discover_workspace,
    initialize_workspace,
    load_raw_source,
)

CREATED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _prepared_review(tmp_path: Path) -> PreparedTransaction:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    source_path = tmp_path / "Source Notes.txt"
    source_path.write_bytes(b"first line\r\nsecond line\n")
    source = load_raw_source(source_path, workspace)
    draft = DraftConcept(
        operation=ChangeOperation.CREATE,
        path=source.concept_id,
        type=ConceptType.SOURCE,
        title="Source notes",
        description="Knowledge about Source notes.",
        tags=["test"],
        body="# Source notes\n\nA grounded claim [1].\n",
        citations=[
            Citation(
                number=1,
                concept_id=source.concept_id,
                start_line=1,
                end_line=2,
            )
        ],
        base_digest=None,
    )
    change_set = ChangeSet(
        summary="Integrated source notes.",
        source_sha256=source.sha256,
        drafts=[draft],
    )
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    return prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        CREATED_AT,
        kind=ReviewKind.INGESTION,
    )


def _managed_tree_bytes(workspace: Workspace) -> dict[str, bytes]:
    roots = (
        workspace.root / "bundlewalker.toml",
        workspace.conventions_file,
        workspace.raw_dir,
        workspace.wiki_dir,
    )
    files: dict[str, bytes] = {}
    for root in roots:
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                files[candidate.relative_to(workspace.root).as_posix()] = candidate.read_bytes()
    return files


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


def test_create_backup_is_verified_and_contains_only_managed_bytes(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    unrelated = workspace.root / "private-note.txt"
    unrelated.write_text("outside managed scope\n", encoding="utf-8")
    git_marker = workspace.root / ".git" / "config"
    git_marker.parent.mkdir()
    git_marker.write_text("private git config\n", encoding="utf-8")
    output = tmp_path / "knowledge.zip"

    verified = create_workspace_backup(
        workspace,
        output,
        clock=lambda: CREATED_AT,
        bundlewalker_version="0.4.0a1",
    )

    assert verified == verify_backup_archive(output)
    archived = {record.path for record in verified.manifest.files}
    assert "bundlewalker.toml" in archived
    assert "conventions.md" in archived
    assert "private-note.txt" not in archived
    assert not any(path.startswith(".git") for path in archived)
    assert not any(path.startswith(".bundlewalker") for path in archived)
    assert stat.S_IMODE(output.stat().st_mode) & 0o077 == 0


def test_create_backup_preserves_every_managed_file_byte_for_byte(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    (workspace.raw_dir / "exact-source.bin").write_bytes(b"first line\r\nsecond line\n\x00\xff")
    before = _managed_tree_bytes(workspace)
    output = tmp_path / "exact-bytes.zip"

    create_workspace_backup(
        workspace,
        output,
        clock=lambda: CREATED_AT,
        bundlewalker_version="0.4.0a1",
    )

    with zipfile.ZipFile(output) as archive:
        archived = {
            name.removeprefix("workspace/"): archive.read(name)
            for name in archive.namelist()
            if name.startswith("workspace/") and not name.endswith("/")
        }
    assert archived == before


def test_create_backup_preserves_custom_paths_and_empty_directories(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    configured = workspace.root / "configured"
    configured.mkdir()
    workspace.wiki_dir.rename(configured / "wiki")
    workspace.raw_dir.rename(configured / "raw")
    workspace.conventions_file.rename(configured / "conventions.md")
    (workspace.root / "bundlewalker.toml").write_text(
        "version = 1\n"
        'wiki_dir = "configured/wiki"\n'
        'raw_dir = "configured/raw"\n'
        'conventions_file = "configured/conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )
    workspace = discover_workspace(workspace.root)

    verified = create_workspace_backup(workspace, tmp_path / "custom.zip")

    assert "configured/raw" in verified.manifest.directories
    assert "configured/conventions.md" in {record.path for record in verified.manifest.files}


def test_create_backup_refuses_existing_or_internal_output(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"keep")

    with pytest.raises(BackupError):
        create_workspace_backup(workspace, existing)
    with pytest.raises(BackupError):
        create_workspace_backup(workspace, workspace.root / "inside.zip")

    assert existing.read_bytes() == b"keep"
    assert not (workspace.root / "inside.zip").exists()


def test_create_backup_rejects_output_ancestor_swap_into_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    outside_ancestor = tmp_path / "outside-ancestor"
    outside_parent = outside_ancestor / "destination"
    outside_parent.mkdir(parents=True)
    parked_ancestor = tmp_path / "outside-ancestor-parked"
    internal_ancestor = workspace.root / "internal-ancestor"
    internal_parent = internal_ancestor / "destination"
    internal_parent.mkdir(parents=True)
    output = outside_parent / "backup.zip"
    original_open = os.open
    swapped = False

    def swap_ancestor_on_parent_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and dir_fd is None and Path(path) == output.parent:
            swapped = True
            outside_ancestor.rename(parked_ancestor)
            outside_ancestor.symlink_to(internal_ancestor, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(backups_module.os, "open", swap_ancestor_on_parent_open)

    with pytest.raises(BackupError, match=r"outside|parent changed"):
        create_workspace_backup(workspace, output)

    outside_ancestor.unlink()
    parked_ancestor.rename(outside_ancestor)
    assert swapped is True
    assert not output.exists()
    assert not (internal_parent / output.name).exists()


def test_create_backup_refuses_pending_review_without_discarding_it(tmp_path: Path) -> None:
    prepared = _prepared_review(tmp_path)

    with pytest.raises(ReviewPendingError):
        create_workspace_backup(prepared.workspace, tmp_path / "blocked.zip")

    assert prepared.transaction_dir.is_dir()
    assert not (tmp_path / "blocked.zip").exists()

    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    discard_pending_review(prepared.workspace, pending.review_id)
    assert get_pending_review(prepared.workspace) is None


def _assert_failed_creation_is_atomic(
    workspace: Workspace,
    output: Path,
    before: dict[str, bytes],
) -> None:
    assert not output.exists()
    assert not list(output.parent.glob(".bundlewalker-backup-*"))
    assert _managed_tree_bytes(workspace) == before


def test_create_backup_cleans_up_after_stream_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "stream-failure.zip"
    before = _managed_tree_bytes(workspace)

    def fail_stream(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected stream failure")

    monkeypatch.setattr(backups_module, "_stream_stable_file", fail_stream)

    with pytest.raises(BackupError, match="read managed data"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


def test_create_backup_does_not_reopen_temporary_path_for_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "secure-temporary.zip"
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"must remain unchanged")
    original_zipfile = zipfile.ZipFile
    intercepted = False

    def replace_temporary_before_zip_open(
        file: Any,
        mode: Any = "r",
        *args: Any,
        **kwargs: Any,
    ) -> zipfile.ZipFile:
        nonlocal intercepted
        if not intercepted and mode == "w":
            intercepted = True
            if isinstance(file, (str, os.PathLike)):
                path_file = cast(str | os.PathLike[str], file)
                temporary = Path(path_file)
                if temporary.name.startswith(".bundlewalker-backup-"):
                    temporary.unlink()
                    temporary.symlink_to(victim)
                    return original_zipfile(path_file, mode, *args, **kwargs)
            raise OSError("stop after secure temporary descriptor handoff")
        return original_zipfile(file, mode, *args, **kwargs)

    monkeypatch.setattr(backups_module.zipfile, "ZipFile", replace_temporary_before_zip_open)

    with pytest.raises(BackupError):
        create_workspace_backup(workspace, output)

    assert intercepted is True
    assert victim.read_bytes() == b"must remain unchanged"
    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_cleans_up_after_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "verification-failure.zip"
    before = _managed_tree_bytes(workspace)

    def fail_verification(_path: Path) -> VerifiedBackup:
        raise BackupVerificationError("injected verification failure")

    monkeypatch.setattr(backups_module, "verify_backup_archive", fail_verification)

    with pytest.raises(BackupVerificationError, match="injected verification"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


def test_create_backup_rejects_temporary_mutation_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "post-verification-mutation.zip"
    original_verify = backups_module.verify_backup_archive

    def mutate_verified_temporary(path: Path) -> VerifiedBackup:
        verified = original_verify(path)
        with path.open("ab") as destination:
            destination.write(b"post-verification mutation")
        return verified

    monkeypatch.setattr(
        backups_module,
        "verify_backup_archive",
        mutate_verified_temporary,
    )

    with pytest.raises(BackupError, match="temporary output changed"):
        create_workspace_backup(workspace, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_cleans_temporary_from_renamed_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    destination = tmp_path / "destination"
    destination.mkdir()
    moved_destination = tmp_path / "destination-moved"
    output = destination / "backup.zip"

    def rename_parent_before_verification(_path: Path) -> VerifiedBackup:
        destination.rename(moved_destination)
        destination.mkdir()
        raise BackupVerificationError("injected parent replacement")

    monkeypatch.setattr(
        backups_module,
        "verify_backup_archive",
        rename_parent_before_verification,
    )

    with pytest.raises(BackupVerificationError, match="parent replacement"):
        create_workspace_backup(workspace, output)

    assert not output.exists()
    assert not list(destination.glob(".bundlewalker-backup-*"))
    assert not list(moved_destination.glob(".bundlewalker-backup-*"))


def test_create_backup_cleans_up_after_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "publication-failure.zip"
    before = _managed_tree_bytes(workspace)

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(backups_module.os, "link", fail_link)

    with pytest.raises(BackupError, match="creation failed"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


def test_create_backup_refuses_insufficient_free_space_without_temporary_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "too-small.zip"
    before = _managed_tree_bytes(workspace)

    def report_no_space(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=0)

    monkeypatch.setattr(
        backups_module.shutil,
        "disk_usage",
        report_no_space,
    )

    with pytest.raises(BackupError, match="insufficient free space"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


def test_create_backup_rejects_invalid_clock_value_as_typed_failure(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    invalid_clock = cast(Callable[[], datetime], lambda: object())

    with pytest.raises(BackupError, match="clock"):
        create_workspace_backup(
            workspace,
            tmp_path / "invalid-clock.zip",
            clock=invalid_clock,
        )

    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_does_not_clobber_concurrent_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "raced.zip"
    before = _managed_tree_bytes(workspace)

    def publish_competitor(
        _source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        assert src_dir_fd == dst_dir_fd
        assert follow_symlinks is False
        assert destination == output.name
        output.write_bytes(b"competitor")
        raise FileExistsError(destination)

    monkeypatch.setattr(backups_module.os, "link", publish_competitor)

    with pytest.raises(BackupError, match="already exists"):
        create_workspace_backup(workspace, output)

    assert output.read_bytes() == b"competitor"
    assert not list(output.parent.glob(".bundlewalker-backup-*"))
    assert _managed_tree_bytes(workspace) == before


def test_create_backup_refuses_output_parent_replacement_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    destination = tmp_path / "destination"
    destination.mkdir()
    moved_destination = tmp_path / "destination-moved"
    output = destination / "backup.zip"
    original_link = os.link

    def publish_then_replace_parent(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        original_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        destination.rename(moved_destination)
        destination.mkdir()

    monkeypatch.setattr(backups_module.os, "link", publish_then_replace_parent)

    with pytest.raises(BackupError, match="output parent"):
        create_workspace_backup(workspace, output)

    assert not output.exists()
    assert not (moved_destination / output.name).exists()
    assert not list(destination.glob(".bundlewalker-backup-*"))
    assert not list(moved_destination.glob(".bundlewalker-backup-*"))


def test_create_backup_rejects_source_mutation_inside_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "publication-mutation.zip"
    original_link = os.link

    def mutate_then_publish(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        descriptor = os.open(source, os.O_WRONLY | os.O_APPEND, dir_fd=src_dir_fd)
        try:
            os.write(descriptor, b"publication mutation")
        finally:
            os.close(descriptor)
        original_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(backups_module.os, "link", mutate_then_publish)

    with pytest.raises(BackupError, match="output changed"):
        create_workspace_backup(workspace, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_rejects_managed_symlink(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (workspace.raw_dir / "linked.txt").symlink_to(outside)
    output = tmp_path / "symlink.zip"
    before = _managed_tree_bytes(workspace)

    with pytest.raises(BackupError, match="symlink"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_create_backup_rejects_managed_fifo(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    os.mkfifo(workspace.raw_dir / "pipe")
    output = tmp_path / "fifo.zip"
    before = _managed_tree_bytes(workspace)

    with pytest.raises(BackupError, match="regular file or directory"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


def test_create_backup_rejects_configured_internal_state_overlap(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    (workspace.root / "bundlewalker.toml").write_text(
        "version = 1\n"
        'wiki_dir = "wiki"\n'
        'raw_dir = "raw"\n'
        'conventions_file = ".bundlewalker/conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )
    workspace = discover_workspace(workspace.root)
    output = tmp_path / "internal.zip"
    before = _managed_tree_bytes(workspace)

    with pytest.raises(BackupError, match="reserved internal state"):
        create_workspace_backup(workspace, output)

    _assert_failed_creation_is_atomic(workspace, output, before)


@pytest.mark.parametrize("mutation", ["replacement", "truncation", "append", "disappearance"])
def test_create_backup_detects_file_mutation_during_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    target = workspace.conventions_file
    original_content = target.read_bytes()
    original_read = os.read
    original_inode = target.stat().st_ino
    parked = target.with_name("parked-conventions.md")
    mutated = False

    def mutate_once(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if not mutated and os.fstat(descriptor).st_ino == original_inode:
            mutated = True
            if mutation == "replacement":
                target.rename(parked)
                target.write_bytes(b"replacement conventions\n")
            elif mutation == "truncation":
                target.write_bytes(b"")
            elif mutation == "append":
                with target.open("ab") as destination:
                    destination.write(b"appended mutation\n")
            else:
                target.unlink()
        return chunk

    monkeypatch.setattr(backups_module.os, "read", mutate_once)
    output = tmp_path / f"{mutation}.zip"

    with pytest.raises(BackupError, match=r"changed|read managed data"):
        create_workspace_backup(workspace, output)

    if mutation == "replacement":
        target.unlink()
        parked.rename(target)
    else:
        target.write_bytes(original_content)
    assert mutated is True
    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_detects_metadata_change_during_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    target = workspace.conventions_file
    original_mode = stat.S_IMODE(target.stat().st_mode)
    original_read = os.read
    original_inode = target.stat().st_ino
    mutated = False

    def chmod_once(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if not mutated and os.fstat(descriptor).st_ino == original_inode:
            mutated = True
            target.chmod(0o600 if original_mode != 0o600 else 0o400)
        return chunk

    monkeypatch.setattr(backups_module.os, "read", chmod_once)
    output = tmp_path / "metadata.zip"

    with pytest.raises(BackupError, match="changed"):
        create_workspace_backup(workspace, output)

    target.chmod(original_mode)
    assert mutated is True
    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_rejects_managed_ancestor_swap_before_file_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    configured = workspace.root / "configured"
    configured.mkdir()
    workspace.wiki_dir.rename(configured / "wiki")
    workspace.raw_dir.rename(configured / "raw")
    workspace.conventions_file.rename(configured / "conventions.md")
    (workspace.root / "bundlewalker.toml").write_text(
        "version = 1\n"
        'wiki_dir = "configured/wiki"\n'
        'raw_dir = "configured/raw"\n'
        'conventions_file = "configured/conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )
    workspace = discover_workspace(workspace.root)
    outside = tmp_path / "outside-managed"
    shutil.copytree(configured, outside)
    (outside / "conventions.md").write_text("outside secret\n", encoding="utf-8")
    parked = workspace.root / "configured-parked"
    original_stream = cast(
        Callable[[zipfile.ZipFile, object], object],
        vars(backups_module)["_stream_stable_file"],
    )
    swapped = False

    def swap_ancestor_then_stream(
        archive: zipfile.ZipFile,
        entry: object,
    ) -> object:
        nonlocal swapped
        if not swapped and getattr(entry, "relative", None) == "configured/conventions.md":
            swapped = True
            configured.rename(parked)
            configured.symlink_to(outside, target_is_directory=True)
        return original_stream(archive, entry)

    monkeypatch.setattr(backups_module, "_stream_stable_file", swap_ancestor_then_stream)
    output = tmp_path / "ancestor-swap.zip"

    with pytest.raises(BackupError):
        create_workspace_backup(workspace, output)

    configured.unlink()
    parked.rename(configured)
    assert swapped is True
    assert not output.exists()
    assert not list(tmp_path.glob(".bundlewalker-backup-*"))


def test_create_backup_holds_quiescent_lock_through_verification_and_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "locked.zip"
    original_verify = backups_module.verify_backup_archive
    original_link = os.link
    observations: list[str] = []

    def assert_lock_is_held(stage: str) -> None:
        descriptor = os.open(workspace.root / ".bundlewalker/transaction.lock", os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        observations.append(stage)

    def inspect_temporary(path: Path) -> VerifiedBackup:
        assert_lock_is_held("verification")
        assert path.parent == output.parent
        assert path.name.startswith(".bundlewalker-backup-")
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        return original_verify(path)

    def inspect_publication(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        assert_lock_is_held("publication")
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(backups_module, "verify_backup_archive", inspect_temporary)
    monkeypatch.setattr(backups_module.os, "link", inspect_publication)

    verified = create_workspace_backup(workspace, output)

    assert verified.archive_path == output
    assert observations == ["verification", "publication"]


def test_create_quiescent_backup_reuses_held_guard(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    output = tmp_path / "guarded.zip"

    with quiescent_workspace(workspace) as quiescent:
        verified = create_quiescent_backup(
            quiescent,
            output,
            clock=lambda: CREATED_AT,
            bundlewalker_version="0.4.0a1",
        )

    assert verified == verify_backup_archive(output)


def test_create_backup_is_deterministic_for_fixed_source_and_metadata(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    create_workspace_backup(
        workspace,
        first,
        clock=lambda: CREATED_AT,
        bundlewalker_version="0.4.0a1",
    )
    create_workspace_backup(
        workspace,
        second,
        clock=lambda: CREATED_AT,
        bundlewalker_version="0.4.0a1",
    )

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_create_backup_refuses_stale_review_and_keeps_it_discardable(tmp_path: Path) -> None:
    prepared = _prepared_review(tmp_path)
    (prepared.workspace.wiki_dir / "index.md").write_text(
        "# Concurrent edit\n",
        encoding="utf-8",
    )
    output = tmp_path / "stale-blocked.zip"

    with pytest.raises(ReviewPendingError):
        create_workspace_backup(prepared.workspace, output)

    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    assert pending.status is ReviewStatus.STALE
    discard_pending_review(prepared.workspace, pending.review_id)
    assert get_pending_review(prepared.workspace) is None
    assert not output.exists()
