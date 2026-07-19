# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker import transactions
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import TransactionDiagnosticStatus, inspect_transaction_state
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


def test_transaction_diagnostics_clean_workspace_creates_no_private_state(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_snapshot(workspace.root)

    result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.CLEAN
    assert _tree_snapshot(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


def test_transaction_diagnostics_pending_review_reads_no_review_or_staged_content(
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
    manifest_path = transaction_dir / "manifest.json"
    lock_path = workspace.root / ".bundlewalker/transaction.lock"
    manifest_descriptor: int | None = None
    opened_paths: list[Path] = []

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
        nonlocal manifest_descriptor
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        opened = Path(os.fsdecode(path))
        opened_paths.append(opened)
        if opened == manifest_path:
            manifest_descriptor = descriptor
        return descriptor

    def manifest_only_read(descriptor: int, size: int) -> bytes:
        assert descriptor == manifest_descriptor
        return original_read(descriptor, size)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guarded_read_bytes)
        guarded.setattr(Path, "read_text", guarded_read_text)
        guarded.setattr(os, "open", tracked_open)
        guarded.setattr(os, "read", manifest_only_read)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert opened_paths == [lock_path, manifest_path]
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


def test_transaction_diagnostics_new_live_reads_no_backup_or_live_content(
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
    before = _tree_snapshot(workspace.root)

    def forbidden_read_bytes(path: Path) -> bytes:
        pytest.fail(f"diagnostics read non-manifest content: {path}")

    def forbidden_read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        pytest.fail(f"diagnostics read non-manifest content: {path}")

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", forbidden_read_bytes)
        guarded.setattr(Path, "read_text", forbidden_read_text)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.INTERRUPTED
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
    private_root = workspace.root / ".bundlewalker"
    original_exists = Path.exists

    def denied_exists(path: Path) -> bool:
        if path == private_root:
            raise PermissionError("diagnostic fixture denied private root")
        return original_exists(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "exists", denied_exists)
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
    private_root = workspace.root / ".bundlewalker"
    lock_path = private_root / "transaction.lock"
    transactions_root = private_root / "transactions"
    transaction_dir = _transaction_dir(workspace)
    manifest_path = transaction_dir / "manifest.json"
    before = _tree_snapshot(workspace.root)
    original_exists = Path.exists
    original_is_symlink = Path.is_symlink
    original_iterdir = Path.iterdir
    original_open = os.open

    def denied_exists(path: Path) -> bool:
        if checkpoint == "transactions-root" and path == transactions_root:
            raise PermissionError("diagnostic fixture denied transaction storage")
        return original_exists(path)

    def denied_is_symlink(path: Path) -> bool:
        if checkpoint == "transaction-dir" and path == transaction_dir:
            raise PermissionError("diagnostic fixture denied transaction entry")
        return original_is_symlink(path)

    def denied_iterdir(path: Path) -> Iterator[Path]:
        if checkpoint == "entries" and path == transactions_root:
            raise PermissionError("diagnostic fixture denied transaction entries")
        return original_iterdir(path)

    def denied_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        decoded = Path(os.fsdecode(path))
        if (checkpoint == "lock" and decoded == lock_path) or (
            checkpoint == "manifest" and decoded == manifest_path
        ):
            raise PermissionError(f"diagnostic fixture denied {checkpoint}")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "exists", denied_exists)
        guarded.setattr(Path, "is_symlink", denied_is_symlink)
        guarded.setattr(Path, "iterdir", denied_iterdir)
        guarded.setattr(os, "open", denied_open)
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
        if os.fsdecode(path) == os.fspath(manifest_path):
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

    def competing_parse_manifest(
        candidate: Workspace,
        transaction_dir: Path,
        content: bytes,
    ) -> object:
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
        return original_parse_manifest(candidate, transaction_dir, content)

    with monkeypatch.context() as guarded:
        guarded.setattr(transactions, "_parse_manifest_bytes", competing_parse_manifest)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert not writer_acquired
