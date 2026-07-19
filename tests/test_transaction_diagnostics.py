# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
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
    before = _tree_snapshot(workspace.root)
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def guarded_read_bytes(path: Path) -> bytes:
        forbidden = {"review.json", "raw-source"}
        assert path.name not in forbidden
        assert "prospective-wiki" not in path.parts
        assert "backup-wiki" not in path.parts
        return original_read_bytes(path)

    def guarded_read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        assert path.name == "manifest.json"
        return original_read_text(path, encoding=encoding, errors=errors, newline=newline)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guarded_read_bytes)
        guarded.setattr(Path, "read_text", guarded_read_text)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert _tree_snapshot(workspace.root) == before


@pytest.mark.parametrize("phase", ["accepted", "raw-persisted", "swapping", "new-live"])
def test_transaction_diagnostics_classifies_interrupted_phases_without_mutation(
    tmp_path: Path,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = phase
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED
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
        guarded.setattr(transactions, "_load_manifest", unexpected_parse)
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
    original_load_manifest = transactions._load_manifest  # pyright: ignore[reportPrivateUsage]
    writer_acquired = False

    def competing_load_manifest(
        candidate: Workspace,
        transaction_dir: Path,
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
        return original_load_manifest(candidate, transaction_dir)

    with monkeypatch.context() as guarded:
        guarded.setattr(transactions, "_load_manifest", competing_load_manifest)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert not writer_acquired
