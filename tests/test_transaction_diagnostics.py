# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from bundlewalker import transactions
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import (
    TransactionDiagnosticStatus,
    inspect_transaction_state,
    recover_transactions,
)
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)


def _workspace_with_review(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    topic = workspace.wiki_dir / "topics" / "agents.md"
    topic.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Agent tools",
                body="# Answer\n\nAgents can use tools [1].\n",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    return workspace


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | str]]:
    snapshot: dict[str, tuple[str, int, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode, b"")
        else:
            snapshot[relative] = ("file", mode, path.read_bytes())
    return snapshot


def _transaction_dir(workspace: Workspace) -> Path:
    return next((workspace.root / ".bundlewalker/transactions").iterdir())


def _manifest_values(transaction_dir: Path) -> dict[str, object]:
    return json.loads((transaction_dir / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest_values(transaction_dir: Path, values: dict[str, object]) -> None:
    (transaction_dir / "manifest.json").write_text(
        json.dumps(values, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _set_phase(workspace: Workspace, phase: str) -> None:
    transaction_dir = _transaction_dir(workspace)
    values = _manifest_values(transaction_dir)
    values["phase"] = phase
    _write_manifest_values(transaction_dir, values)


def _declare_raw_payload(workspace: Workspace) -> None:
    transaction_dir = _transaction_dir(workspace)
    content = b"diagnostic raw payload\n"
    (transaction_dir / "raw-source").write_bytes(content)
    values = _manifest_values(transaction_dir)
    values["raw_path"] = "raw/diagnostic.txt"
    values["raw_sha256"] = hashlib.sha256(content).hexdigest()
    _write_manifest_values(transaction_dir, values)


def _materialize_phase_topology(workspace: Workspace, phase: str) -> None:
    transaction_dir = _transaction_dir(workspace)
    _set_phase(workspace, phase)
    if phase == "new-live":
        workspace.wiki_dir.rename(transaction_dir / "backup-wiki")
        (transaction_dir / "prospective-wiki").rename(workspace.wiki_dir)


def _convert_to_legacy(workspace: Workspace) -> None:
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()


def _use_nested_live_wiki(workspace: Workspace) -> Workspace:
    parent = workspace.root / "configured"
    parent.mkdir()
    workspace.wiki_dir.rename(parent / "live-wiki")
    return replace(
        workspace,
        config=replace(workspace.config, wiki_dir="configured/live-wiki"),
    )


def test_transaction_diagnostics_clean_workspace_creates_no_private_state(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_snapshot(workspace.root)

    result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.CLEAN
    assert _tree_snapshot(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


def test_transaction_diagnostics_pending_review_reads_only_manifest_and_identity_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    _declare_raw_payload(workspace)
    assert (transaction_dir / "raw-source").is_file()
    assert (transaction_dir / "identity.json").read_bytes()
    assert (transaction_dir / "review.json").read_bytes()
    assert next((transaction_dir / "prospective-wiki").rglob("*.md")).read_bytes()
    assert next(workspace.wiki_dir.rglob("*.md")).read_bytes()
    before = _tree_snapshot(workspace.root)
    original_open = os.open
    original_read = os.read
    manifest_descriptor: int | None = None
    identity_descriptor: int | None = None
    forbidden_names = {
        "backup-wiki",
        "prospective-wiki",
        "raw-source",
        "review.json",
        workspace.wiki_dir.name,
    }

    def guarded_read_bytes(path: Path) -> bytes:
        pytest.fail(f"diagnostics read content through Path.read_bytes: {path}")

    def guarded_read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        pytest.fail(f"diagnostics read content through Path.read_text: {path}")

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal identity_descriptor, manifest_descriptor
        opened = Path(os.fsdecode(path))
        assert opened.name not in forbidden_names
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if opened.name == "manifest.json":
            manifest_descriptor = descriptor
        elif opened.name == "identity.json":
            identity_descriptor = descriptor
            assert flags & getattr(os, "O_NOFOLLOW", 0)
            assert flags & getattr(os, "O_NONBLOCK", 0)
        return descriptor

    def metadata_only_read(descriptor: int, size: int) -> bytes:
        assert descriptor in {manifest_descriptor, identity_descriptor}
        return original_read(descriptor, size)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guarded_read_bytes)
        guarded.setattr(Path, "read_text", guarded_read_text)
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "read", metadata_only_read)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert manifest_descriptor is not None
    assert identity_descriptor is not None
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize("phase", ["accepted", "raw-persisted", "swapping", "new-live"])
def test_transaction_diagnostics_classifies_interrupted_phases_without_mutation(
    tmp_path: Path,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _materialize_phase_topology(workspace, phase)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    ("schema_version", "phase"),
    [(1, "prepared"), (1, "raw-persisted"), (2, "prepared"), (2, "accepted")],
)
@pytest.mark.parametrize("field", ["base_wiki_digest", "prospective_digest"])
@pytest.mark.parametrize("mutation", ["missing", "null"])
def test_diagnostics_and_recovery_require_manifest_digest_identity(
    tmp_path: Path,
    schema_version: int,
    phase: str,
    field: str,
    mutation: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _set_phase(workspace, phase)
    if schema_version == 1:
        _convert_to_legacy(workspace)
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    if mutation == "missing":
        manifest.pop(field)
    else:
        manifest[field] = None
    _write_manifest_values(transaction_dir, manifest)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before

    with pytest.raises(
        transactions.TransactionError,
        match=r"manifest identities do not match transaction(?: review)? identity",
    ):
        recover_transactions(workspace)
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize("field", ["base_wiki_digest", "prospective_digest"])
def test_transaction_diagnostics_authenticates_identity_against_manifest(
    tmp_path: Path,
    field: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity[field] = "f" * 64
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before

    with pytest.raises(
        transactions.TransactionError,
        match=r"manifest identities do not match transaction(?: review)? identity",
    ):
        recover_transactions(workspace)
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    ("schema_version", "phase"),
    [
        (1, "prepared"),
        (1, "raw-persisted"),
        (1, "swapping"),
        (1, "new-live"),
        (2, "prepared"),
        (2, "accepted"),
        (2, "raw-persisted"),
        (2, "swapping"),
        (2, "new-live"),
    ],
)
def test_transaction_diagnostics_enforces_schema_identity_rules_in_every_phase(
    tmp_path: Path,
    schema_version: int,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _materialize_phase_topology(workspace, phase)
    if schema_version == 1:
        _convert_to_legacy(workspace)
    transaction_dir = _transaction_dir(workspace)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if schema_version == 1:
        identity["review_digest"] = "f" * 64
    else:
        identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    "content",
    [
        b"not json\n",
        b"[]\n",
        b'{"base_wiki_digest": "bad"}\n',
        b"{" + b'"base_wiki_digest":' + b"9" * 5_000 + b"}",
    ],
    ids=["invalid-json", "wrong-json-kind", "malformed-digest", "integer-limit"],
)
def test_transaction_diagnostics_rejects_malformed_identity_metadata(
    tmp_path: Path,
    content: bytes,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    identity_path = _transaction_dir(workspace) / "identity.json"
    identity_path.write_bytes(content)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_oversized_identity_with_bounded_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    identity_path = _transaction_dir(workspace) / "identity.json"
    identity_path.write_bytes(b"x" * 4_098)
    original_open = os.open
    original_read = os.read
    identity_descriptor: int | None = None
    requested_bytes = 0

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal identity_descriptor
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == "identity.json" and dir_fd is not None:
            identity_descriptor = descriptor
        return descriptor

    def bounded_read(descriptor: int, size: int) -> bytes:
        nonlocal requested_bytes
        if descriptor == identity_descriptor:
            requested_bytes += size
            assert requested_bytes <= 4_097
        return original_read(descriptor, size)

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "read", bounded_read)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.MALFORMED
    assert identity_descriptor is not None
    assert requested_bytes <= 4_097


def test_transaction_diagnostics_accepts_identity_at_exact_size_limit(tmp_path: Path) -> None:
    workspace = _workspace_with_review(tmp_path)
    identity_path = _transaction_dir(workspace) / "identity.json"
    content = identity_path.read_bytes()
    assert len(content) < 4_096
    identity_path.write_bytes(content + b" " * (4_096 - len(content)))

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.PENDING


@pytest.mark.parametrize(
    ("schema_version", "phase"),
    [
        (1, "prepared"),
        (1, "raw-persisted"),
        (2, "prepared"),
        (2, "accepted"),
        (2, "raw-persisted"),
    ],
)
def test_transaction_diagnostics_rejects_missing_live_wiki_before_swapping(
    tmp_path: Path,
    schema_version: int,
    phase: str,
) -> None:
    workspace = _use_nested_live_wiki(_workspace_with_review(tmp_path))
    _set_phase(workspace, phase)
    if schema_version == 1:
        _convert_to_legacy(workspace)
    shutil.rmtree(workspace.wiki_dir)
    (workspace.root / "wiki").mkdir()

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED


@pytest.mark.parametrize("schema_version", [1, 2])
@pytest.mark.parametrize("phase", ["swapping", "new-live"])
def test_transaction_diagnostics_allows_recoverable_missing_live_wiki_after_swap_starts(
    tmp_path: Path,
    schema_version: int,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    old_wiki = _tree_snapshot(workspace.wiki_dir)
    _set_phase(workspace, phase)
    workspace.wiki_dir.rename(transaction_dir / "backup-wiki")
    if phase == "new-live":
        (transaction_dir / "prospective-wiki").rename(workspace.wiki_dir)
        shutil.rmtree(workspace.wiki_dir)
    if schema_version == 1:
        _convert_to_legacy(workspace)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED

    recover_transactions(workspace)
    assert _tree_snapshot(workspace.wiki_dir) == old_wiki


@pytest.mark.parametrize(
    ("schema_version", "phase", "live_kind"),
    [
        (2, "prepared", "symlink"),
        (1, "raw-persisted", "regular"),
        (2, "accepted", "fifo"),
        (1, "swapping", "socket"),
        (2, "new-live", "symlink"),
    ],
)
def test_transaction_diagnostics_rejects_unsafe_live_wiki_kinds(
    tmp_path: Path,
    schema_version: int,
    phase: str,
    live_kind: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    _set_phase(workspace, phase)
    if phase in {"swapping", "new-live"}:
        workspace.wiki_dir.rename(transaction_dir / "backup-wiki")
    if phase == "new-live":
        (transaction_dir / "prospective-wiki").rename(workspace.wiki_dir)
    if workspace.wiki_dir.is_dir():
        shutil.rmtree(workspace.wiki_dir)
    if schema_version == 1:
        _convert_to_legacy(workspace)

    live_socket: socket.socket | None = None
    short_socket_root: Path | None = None
    if live_kind == "symlink":
        outside = tmp_path / f"outside-live-{phase}"
        outside.mkdir()
        workspace.wiki_dir.symlink_to(outside, target_is_directory=True)
    elif live_kind == "regular":
        workspace.wiki_dir.write_bytes(b"not a live wiki directory\n")
    elif live_kind == "fifo":
        os.mkfifo(workspace.wiki_dir)
    else:
        short_socket_root = Path(tempfile.mkdtemp(prefix="bw-sock-", dir="/tmp"))
        (short_socket_root / "root").symlink_to(workspace.root, target_is_directory=True)
        live_socket = socket.socket(socket.AF_UNIX)
        live_socket.bind(os.fspath(short_socket_root / "root" / workspace.wiki_dir.name))
    try:
        assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    finally:
        if live_socket is not None:
            live_socket.close()
        if short_socket_root is not None:
            shutil.rmtree(short_socket_root)


def test_transaction_diagnostics_classifies_legacy_prepared_as_interrupted(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_legacy_manifest_with_review_artifact(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    ("node_name", "replacement_kind"),
    [
        ("identity.json", "missing"),
        ("identity.json", "wrong-kind"),
        ("identity.json", "symlink"),
        ("prospective-wiki", "missing"),
        ("prospective-wiki", "wrong-kind"),
        ("prospective-wiki", "symlink"),
        ("backup-wiki", "wrong-kind"),
        ("backup-wiki", "symlink"),
        ("raw-source", "wrong-kind"),
        ("raw-source", "symlink"),
    ],
)
def test_transaction_diagnostics_rejects_invalid_legacy_prepared_fixed_nodes(
    tmp_path: Path,
    node_name: str,
    replacement_kind: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()

    path = transaction_dir / node_name
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    if replacement_kind == "wrong-kind":
        if node_name in {"identity.json", "raw-source"}:
            path.mkdir()
        else:
            path.write_bytes(b"wrong fixed-node kind\n")
    elif replacement_kind == "symlink":
        target = tmp_path / f"outside-legacy-{node_name}"
        if node_name == "prospective-wiki":
            target.mkdir()
        else:
            target.write_bytes(b"outside fixed-node content\n")
        path.symlink_to(target, target_is_directory=node_name == "prospective-wiki")
    before = _tree_snapshot(tmp_path)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(tmp_path) == before


def test_transaction_diagnostics_accepts_legacy_prepared_regular_raw_payload(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    _declare_raw_payload(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_missing_declared_legacy_raw_payload(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    _declare_raw_payload(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()
    (transaction_dir / "raw-source").unlink()

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED


@pytest.mark.parametrize("replacement_kind", ["valid", "missing", "wrong-kind", "symlink"])
def test_transaction_diagnostics_validates_legacy_new_live_backup_topology(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _materialize_phase_topology(workspace, "new-live")
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest["schema_version"] = 1
    _write_manifest_values(transaction_dir, manifest)
    identity_path = transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (transaction_dir / "review.json").unlink()
    backup = transaction_dir / "backup-wiki"
    if replacement_kind != "valid":
        shutil.rmtree(backup)
    if replacement_kind == "wrong-kind":
        backup.write_bytes(b"wrong fixed-node kind\n")
    elif replacement_kind == "symlink":
        outside = tmp_path / "outside-legacy-backup"
        outside.mkdir()
        backup.symlink_to(outside, target_is_directory=True)

    expected = (
        TransactionDiagnosticStatus.INTERRUPTED
        if replacement_kind == "valid"
        else TransactionDiagnosticStatus.MALFORMED
    )
    assert inspect_transaction_state(workspace) is expected


@pytest.mark.parametrize(
    ("node_name", "phase"),
    [
        ("identity.json", "prepared"),
        ("review.json", "accepted"),
        ("raw-source", "raw-persisted"),
        ("prospective-wiki", "swapping"),
        ("backup-wiki", "new-live"),
    ],
)
def test_transaction_diagnostics_rejects_missing_required_schema_v2_nodes(
    tmp_path: Path,
    node_name: str,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _declare_raw_payload(workspace)
    _materialize_phase_topology(workspace, phase)
    path = _transaction_dir(workspace) / node_name
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize("replacement_kind", ["wrong-kind", "symlink"])
@pytest.mark.parametrize(
    ("node_name", "phase"),
    [
        ("identity.json", "prepared"),
        ("review.json", "accepted"),
        ("raw-source", "raw-persisted"),
        ("prospective-wiki", "swapping"),
        ("backup-wiki", "new-live"),
    ],
)
def test_transaction_diagnostics_rejects_unsafe_required_schema_v2_nodes(
    tmp_path: Path,
    node_name: str,
    phase: str,
    replacement_kind: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _declare_raw_payload(workspace)
    _materialize_phase_topology(workspace, phase)
    path = _transaction_dir(workspace) / node_name
    expected_directory = path.is_dir()
    if expected_directory:
        shutil.rmtree(path)
    else:
        path.unlink()
    if replacement_kind == "wrong-kind":
        if expected_directory:
            path.write_bytes(b"wrong fixed-node kind\n")
        else:
            path.mkdir()
    else:
        target = tmp_path / f"outside-{node_name}"
        if expected_directory:
            target.mkdir()
        else:
            target.write_bytes(b"outside fixed-node content\n")
        path.symlink_to(target, target_is_directory=expected_directory)
    before = _tree_snapshot(tmp_path)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(tmp_path) == before


def test_transaction_diagnostics_rejects_new_live_with_pre_swap_topology(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _set_phase(workspace, "new-live")
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_new_live_reads_only_manifest_and_identity_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _declare_raw_payload(workspace)
    _materialize_phase_topology(workspace, "new-live")
    transaction_dir = _transaction_dir(workspace)
    backup_file = next((transaction_dir / "backup-wiki").rglob("*.md"))
    live_file = next(workspace.wiki_dir.rglob("*.md"))
    assert backup_file.read_bytes()
    assert live_file.read_bytes()
    assert (transaction_dir / "raw-source").read_bytes()
    assert (transaction_dir / "identity.json").read_bytes()
    assert (transaction_dir / "review.json").read_bytes()
    before = _tree_snapshot(workspace.root)
    original_open = os.open
    original_read = os.read
    manifest_descriptor: int | None = None
    identity_descriptor: int | None = None
    forbidden_names = {
        "backup-wiki",
        "prospective-wiki",
        "raw-source",
        "review.json",
        workspace.wiki_dir.name,
    }

    def forbidden_read_bytes(path: Path) -> bytes:
        pytest.fail(f"diagnostics read non-manifest content: {path}")

    def forbidden_read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        pytest.fail(f"diagnostics read non-manifest content: {path}")

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal identity_descriptor, manifest_descriptor
        opened = Path(os.fsdecode(path))
        assert opened.name not in forbidden_names
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if opened.name == "manifest.json":
            manifest_descriptor = descriptor
        elif opened.name == "identity.json":
            identity_descriptor = descriptor
            assert flags & getattr(os, "O_NOFOLLOW", 0)
            assert flags & getattr(os, "O_NONBLOCK", 0)
        return descriptor

    def metadata_only_read(descriptor: int, size: int) -> bytes:
        assert descriptor in {manifest_descriptor, identity_descriptor}
        return original_read(descriptor, size)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", forbidden_read_bytes)
        guarded.setattr(Path, "read_text", forbidden_read_text)
        guarded.setattr(os, "open", guarded_open)
        guarded.setattr(os, "read", metadata_only_read)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.INTERRUPTED
    assert manifest_descriptor is not None
    assert identity_descriptor is not None
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_symlinked_transaction_storage(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    private = workspace.root / ".bundlewalker"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (private / "transactions").symlink_to(outside, target_is_directory=True)
    before = _tree_snapshot(tmp_path)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(tmp_path) == before


def test_transaction_diagnostics_contains_private_root_permission_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    original_open = os.open

    def denied_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fsdecode(path) == ".bundlewalker":
            raise PermissionError("diagnostic fixture denied private root")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", denied_open)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.MALFORMED


@pytest.mark.parametrize(
    "checkpoint",
    ["lock", "transactions-root", "entries", "transaction-dir", "manifest"],
)
def test_transaction_diagnostics_contains_snapshot_permission_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    before = _tree_snapshot(workspace.root)
    original_open = os.open
    original_scandir = os.scandir
    transactions_descriptor: int | None = None

    def denied_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal transactions_descriptor
        decoded = os.fsdecode(path)
        denied_names = {
            "lock": "transaction.lock",
            "transactions-root": "transactions",
            "transaction-dir": transaction_dir.name,
            "manifest": "manifest.json",
        }
        if checkpoint in denied_names and decoded == denied_names[checkpoint]:
            raise PermissionError(f"diagnostic fixture denied {checkpoint}")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if decoded == "transactions":
            transactions_descriptor = descriptor
        return descriptor

    def denied_scandir(
        path: int,
    ) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        if checkpoint == "entries" and path == transactions_descriptor:
            raise PermissionError("diagnostic fixture denied transaction entries")
        return cast(AbstractContextManager[Iterator[os.DirEntry[str]]], original_scandir(path))

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", denied_open)
        guarded.setattr(os, "scandir", denied_scandir)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_multiple_pending_reviews(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transactions_root = workspace.root / ".bundlewalker/transactions"
    original = next(transactions_root.iterdir())
    duplicate = transactions_root / ("f" * 32)
    shutil.copytree(original, duplicate)
    manifest_path = duplicate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["transaction_id"] = "f" * 32
    manifest["prospective_path"] = f".bundlewalker/transactions/{'f' * 32}/prospective-wiki"
    manifest["backup_path"] = f".bundlewalker/transactions/{'f' * 32}/backup-wiki"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_excess_transaction_entries_before_opening_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    transactions_root = workspace.root / ".bundlewalker/transactions"
    transactions_root.mkdir(parents=True)
    for index in range(65):
        (transactions_root / f"{index:032x}").mkdir()
    original_open = os.open
    transactions_descriptor: int | None = None

    def forbid_transaction_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal transactions_descriptor
        decoded = os.fsdecode(path)
        if transactions_descriptor is not None and dir_fd == transactions_descriptor:
            pytest.fail("diagnostics opened an entry after the enumeration limit was exceeded")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if decoded == "transactions":
            transactions_descriptor = descriptor
        return descriptor

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", forbid_transaction_open)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.MALFORMED


def test_transaction_diagnostics_rejects_excess_quarantine_name_enumeration(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    for index in range(65):
        (transaction_dir / f"untrusted-{index:02d}").write_bytes(b"")

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED


def test_transaction_diagnostics_rejects_mixed_pending_and_interrupted_entries(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transactions_root = workspace.root / ".bundlewalker/transactions"
    original = _transaction_dir(workspace)
    duplicate = transactions_root / ("f" * 32)
    shutil.copytree(original, duplicate)
    manifest = _manifest_values(duplicate)
    manifest["transaction_id"] = "f" * 32
    manifest["prospective_path"] = f".bundlewalker/transactions/{'f' * 32}/prospective-wiki"
    manifest["backup_path"] = f".bundlewalker/transactions/{'f' * 32}/backup-wiki"
    manifest["phase"] = "accepted"
    _write_manifest_values(duplicate, manifest)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_id", "f" * 32),
        ("prospective_path", ".bundlewalker/transactions/elsewhere/prospective-wiki"),
        ("backup_path", ".bundlewalker/transactions/elsewhere/backup-wiki"),
    ],
)
def test_transaction_diagnostics_validates_manifest_transaction_relationships(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    manifest = _manifest_values(transaction_dir)
    manifest[field] = value
    _write_manifest_values(transaction_dir, manifest)
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_oversized_manifest_without_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    manifest_path.write_bytes(b"{" + b"x" * 1_048_576 + b"}")
    before = _tree_snapshot(workspace.root)

    def unexpected_parse(*_args: object, **_kwargs: object) -> object:
        pytest.fail("oversized manifest was parsed")

    with monkeypatch.context() as guarded:
        guarded.setattr(transactions, "_parse_manifest_bytes", unexpected_parse)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_fifo_manifest_without_blocking(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = _transaction_dir(workspace) / "manifest.json"
    manifest_path.unlink()
    os.mkfifo(manifest_path)
    command = (
        "from pathlib import Path\n"
        "from bundlewalker.transactions import inspect_transaction_state\n"
        "from bundlewalker.workspace import discover_workspace\n"
        "workspace = discover_workspace(Path(__import__('sys').argv[1]))\n"
        "print(inspect_transaction_state(workspace).value)\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command, os.fspath(workspace.root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert completed.stdout.strip() == TransactionDiagnosticStatus.MALFORMED


@pytest.mark.parametrize(
    "content",
    [
        b"[" * 10_000 + b"]" * 10_000,
        b'{"schema_version":' + b"9" * 5_000 + b"}",
    ],
    ids=["deep-nesting", "oversized-integer-token"],
)
def test_transaction_diagnostics_contains_bounded_json_parser_exhaustion(
    tmp_path: Path,
    content: bytes,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = _transaction_dir(workspace) / "manifest.json"
    assert len(content) < 1_048_576
    manifest_path.write_bytes(content)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED


def test_legacy_recovery_propagates_oversized_integer_before_mutation(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    _convert_to_legacy(workspace)
    manifest_path = _transaction_dir(workspace) / "manifest.json"
    content = manifest_path.read_bytes().replace(
        b'"schema_version": 1',
        b'"schema_version": ' + b"9" * 5_000,
        1,
    )
    assert len(content) < 1_048_576
    manifest_path.write_bytes(content)
    before = _tree_snapshot(workspace.root)

    with pytest.raises(ValueError, match="integer string conversion"):
        recover_transactions(workspace)

    assert _tree_snapshot(workspace.root) == before
    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_accepts_manifest_at_exact_size_limit(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    content = manifest_path.read_bytes()
    assert len(content) < 1_048_576
    manifest_path.write_bytes(content + b" " * (1_048_576 - len(content)))
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.PENDING
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_reads_only_the_opened_manifest_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    replacement = manifest_path.with_name("replacement.json")
    replacement.write_bytes(b"not valid JSON\n")
    original_open = os.open
    original_fstat = os.fstat
    original_read = os.read
    manifest_descriptor: int | None = None
    manifest_opens = 0
    requested_bytes = 0
    replaced = False

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal manifest_descriptor, manifest_opens
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if os.fsdecode(path) == "manifest.json" and dir_fd is not None:
            manifest_descriptor = descriptor
            manifest_opens += 1
            assert flags & getattr(os, "O_NOFOLLOW", 0)
        return descriptor

    def replace_after_fstat(descriptor: int) -> os.stat_result:
        nonlocal replaced
        metadata = original_fstat(descriptor)
        if descriptor == manifest_descriptor and not replaced:
            os.replace(replacement, manifest_path)
            replaced = True
        return metadata

    def bounded_read(descriptor: int, size: int) -> bytes:
        nonlocal requested_bytes
        if descriptor == manifest_descriptor:
            requested_bytes += size
            assert requested_bytes <= 1_048_577
        return original_read(descriptor, size)

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "fstat", replace_after_fstat)
        guarded.setattr(os, "read", bounded_read)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert replaced
    assert manifest_opens == 1
    assert requested_bytes <= 1_048_577


def test_transaction_diagnostics_reports_existing_busy_lock_without_mutation(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    lock_path = workspace.root / ".bundlewalker" / "transaction.lock"
    descriptor = os.open(lock_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = _tree_snapshot(workspace.root)

        assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.BUSY
        assert _tree_snapshot(workspace.root) == before
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_transaction_diagnostics_rejects_unsafe_lock_nodes_without_mutation(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    lock_path = workspace.root / ".bundlewalker" / "transaction.lock"
    lock_path.unlink()
    if kind == "directory":
        lock_path.mkdir()
    else:
        outside = tmp_path / "outside-lock"
        outside.write_bytes(b"")
        lock_path.symlink_to(outside)
    before = _tree_snapshot(tmp_path)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(tmp_path) == before


def test_transaction_diagnostics_never_enters_recovery_or_mutation_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)

    def forbidden_call(*_args: object, **_kwargs: object) -> object:
        pytest.fail("transaction diagnostics entered a recovery or mutation path")

    with monkeypatch.context() as guarded:
        for name in (
            "workspace_lock",
            "recover_transactions",
            "_recover_transactions_locked",
            "_recover_transaction",
            "_ensure_transactions_root",
        ):
            guarded.setattr(transactions, name, forbidden_call)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING


def test_transaction_diagnostics_holds_shared_lock_while_reading_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    lock_path = workspace.root / ".bundlewalker" / "transaction.lock"
    original_parse_manifest = transactions._parse_manifest_bytes  # pyright: ignore[reportPrivateUsage]
    writer_acquired = False

    def competing_parse_manifest(content: bytes) -> object:
        nonlocal writer_acquired
        descriptor = os.open(lock_path, os.O_RDONLY)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                writer_acquired = True
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
        return original_parse_manifest(content)

    with monkeypatch.context() as guarded:
        guarded.setattr(transactions, "_parse_manifest_bytes", competing_parse_manifest)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert not writer_acquired


def test_transaction_diagnostics_stays_on_opened_tree_during_private_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transaction_dir = _transaction_dir(workspace)
    private_root = workspace.root / ".bundlewalker"
    retained_private_root = workspace.root / ".bundlewalker-retained"
    outside_private_root = tmp_path / "outside-private"
    shutil.copytree(private_root, outside_private_root)
    outside_manifest = next((outside_private_root / "transactions").glob("*/manifest.json"))
    outside_manifest.write_bytes(b"not valid JSON\n")
    original_open = os.open
    swapped = False

    def swap_before_transaction_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if os.fsdecode(path) == transaction_dir.name and dir_fd is not None and not swapped:
            private_root.rename(retained_private_root)
            private_root.symlink_to(outside_private_root, target_is_directory=True)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as guarded:
        guarded.setattr(os, "open", swap_before_transaction_open)
        result = inspect_transaction_state(workspace)

    assert swapped
    assert result is TransactionDiagnosticStatus.PENDING
