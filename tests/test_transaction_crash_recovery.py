# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.transactions as transactions
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    ReviewStatus,
    apply_pending_review,
    get_pending_review,
    prepare_transaction,
    recover_transactions,
)
from bundlewalker.workspace import (
    RawSource,
    Workspace,
    discover_workspace,
    initialize_workspace,
    load_raw_source,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
CRASH_EXIT = 86


def _prepare_review(workspace: Workspace) -> tuple[PreparedTransaction, RawSource]:
    source_path = workspace.root.parent / "crash-source.txt"
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
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    return prepared, source


def _child(workspace_root: Path, phase: str, review_id: str | None) -> None:
    original = transactions._write_manifest  # pyright: ignore[reportPrivateUsage]

    def write_then_exit(
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        original(transaction_dir, manifest)
        if manifest.phase == phase:
            os._exit(CRASH_EXIT)

    transactions._write_manifest = write_then_exit  # pyright: ignore[reportPrivateUsage]
    workspace = discover_workspace(workspace_root)
    if phase == "prepared":
        _prepare_review(workspace)
        raise AssertionError("prepared manifest hook did not terminate the child")
    if review_id is None:
        raise AssertionError("accepted-phase worker requires a review ID")
    apply_pending_review(workspace, review_id)
    raise AssertionError(f"{phase} manifest hook did not terminate the child")


def _run_child(workspace: Workspace, phase: str, review_id: str | None) -> None:
    environment = os.environ.copy()
    environment["BUNDLEWALKER_CRASH_WORKER"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            str(workspace.root),
            phase,
            review_id or "-",
        ],
        check=False,
        env=environment,
        timeout=30,
    )
    assert result.returncode == CRASH_EXIT


if __name__ == "__main__" and os.environ.get("BUNDLEWALKER_CRASH_WORKER") == "1":
    root = Path(sys.argv[1])
    selected_phase = sys.argv[2]
    selected_review = None if sys.argv[3] == "-" else sys.argv[3]
    _child(root, selected_phase, selected_review)


def test_abrupt_exit_after_prepared_retains_review_and_live_base(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    base = _tree_bytes(workspace.wiki_dir)

    _run_child(workspace, "prepared", None)
    recover_transactions(workspace)

    pending = get_pending_review(workspace)
    assert pending is not None
    assert pending.status is ReviewStatus.PENDING
    assert _tree_bytes(workspace.wiki_dir) == base
    assert not any(workspace.raw_dir.rglob("*"))
    first = _tree_bytes(workspace.root / ".bundlewalker/transactions")
    recover_transactions(workspace)
    assert _tree_bytes(workspace.root / ".bundlewalker/transactions") == first


@pytest.mark.parametrize("phase", ["accepted", "raw-persisted", "swapping", "new-live"])
def test_abrupt_exit_after_accepted_phase_completes_exact_commit(
    tmp_path: Path,
    phase: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    prepared, source = _prepare_review(workspace)
    expected_wiki = _tree_bytes(prepared.prospective_wiki)

    _run_child(workspace, phase, prepared.transaction_id)
    recover_transactions(workspace)

    assert get_pending_review(workspace) is None
    assert _tree_bytes(workspace.wiki_dir) == expected_wiki
    assert (workspace.root / source.stored_relative_path).read_bytes() == source.content
    transactions_root = workspace.root / ".bundlewalker/transactions"
    assert not any(transactions_root.iterdir())
    committed = _tree_bytes(workspace.root)
    recover_transactions(workspace)
    assert _tree_bytes(workspace.root) == committed


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
