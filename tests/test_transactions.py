from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.transactions as transactions
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
from bundlewalker.errors import TransactionError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    commit_transaction,
    discard_transaction,
    prepare_transaction,
    recover_transactions,
)
from bundlewalker.workspace import RawSource, Workspace, initialize_workspace, load_raw_source

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _transaction_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_dir():
            digest.update(b"D")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
        elif path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            digest.update(b"F")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    return digest.hexdigest()


def _draft(
    *,
    path: str,
    type: ConceptType,
    title: str,
    body: str,
    operation: ChangeOperation = ChangeOperation.CREATE,
    base_digest: str | None = None,
    citations: list[Citation] | None = None,
) -> DraftConcept:
    return DraftConcept(
        operation=operation,
        path=path,
        type=type,
        title=title,
        description=f"Knowledge about {title}.",
        tags=["test"],
        body=body,
        citations=citations or [],
        base_digest=base_digest,
    )


def _ingestion(
    tmp_path: Path,
) -> tuple[Workspace, RawSource, ChangeSet, ChangeValidationContext]:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    input_path = tmp_path / "Source Notes.txt"
    input_path.write_bytes(b"first line\r\nsecond line\n")
    source = load_raw_source(input_path, workspace)
    source_draft = _draft(
        path=source.concept_id,
        type=ConceptType.SOURCE,
        title="Source notes",
        body="# Source notes\n\nA grounded claim [1].\n",
        citations=[
            Citation(
                number=1,
                concept_id=source.concept_id,
                start_line=1,
                end_line=2,
            )
        ],
    )
    change_set = ChangeSet(
        summary="Integrated source notes.",
        source_sha256=source.sha256,
        drafts=[source_draft],
    )
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    return workspace, source, change_set, context


def _prepare(tmp_path: Path) -> tuple[PreparedTransaction, RawSource]:
    workspace, source, change_set, context = _ingestion(tmp_path)
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
    )
    return prepared, source


def _manifest(prepared: PreparedTransaction) -> dict[str, object]:
    return json.loads((prepared.transaction_dir / "manifest.json").read_text(encoding="utf-8"))


def _set_phase(prepared: PreparedTransaction, phase: str) -> None:
    manifest_path = prepared.transaction_dir / "manifest.json"
    values = _manifest(prepared)
    values["phase"] = phase
    manifest_path.write_text(
        json.dumps(values, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_raw(prepared: PreparedTransaction, source: RawSource) -> None:
    destination = prepared.workspace.root / source.stored_relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.content)


def test_prepare_stages_a_complete_review_without_live_writes(tmp_path: Path) -> None:
    workspace, source, change_set, context = _ingestion(tmp_path)
    live_wiki = _tree_bytes(workspace.wiki_dir)
    live_raw = _tree_bytes(workspace.raw_dir)
    files_before = set(_tree_bytes(workspace.root))

    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
    )

    added_files = set(_tree_bytes(workspace.root)) - files_before
    transaction_prefix = f".bundlewalker/transactions/{prepared.transaction_id}/"
    assert added_files
    assert all(path.startswith(transaction_prefix) for path in added_files)
    assert _tree_bytes(workspace.wiki_dir) == live_wiki
    assert _tree_bytes(workspace.raw_dir) == live_raw
    assert prepared.diff
    assert "--- /dev/null" in prepared.diff
    assert f"+++ wiki/{source.concept_id}.md" in prepared.diff
    assert "+# Knowledge Update Log" not in prepared.diff
    assert prepared.raw_source is source
    assert prepared.change_set is change_set
    assert prepared.summary == change_set.summary

    values = _manifest(prepared)
    assert values["schema_version"] == 1
    assert values["transaction_id"] == prepared.transaction_id
    assert values["phase"] == "prepared"
    assert values["raw_path"] == source.stored_relative_path.as_posix()
    assert values["raw_sha256"] == source.sha256
    assert values["summary"] == change_set.summary
    assert isinstance(values["base_wiki_digest"], str)
    assert len(values["base_wiki_digest"]) == 64
    assert values["drafts"] == [
        {
            "base_digest": None,
            "operation": "create",
            "path": source.concept_id,
        }
    ]
    assert (prepared.transaction_dir / "raw-source").read_bytes() == source.content
    assert not (prepared.transaction_dir / "validation-workspace").exists()


def test_discard_removes_only_the_prepared_transaction(tmp_path: Path) -> None:
    prepared, _ = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    live_raw = _tree_bytes(prepared.workspace.raw_dir)

    discard_transaction(prepared)

    assert not prepared.transaction_dir.exists()
    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki
    assert _tree_bytes(prepared.workspace.raw_dir) == live_raw


def test_commit_persists_exact_raw_bytes_and_the_reviewed_wiki(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    prospective = _tree_bytes(prepared.prospective_wiki)

    commit_transaction(prepared)

    assert (prepared.workspace.root / source.stored_relative_path).read_bytes() == source.content
    assert _tree_bytes(prepared.workspace.wiki_dir) == prospective
    assert not has_errors(lint_bundle(prepared.workspace.wiki_dir, prepared.workspace.root))
    assert not prepared.transaction_dir.exists()


def test_transaction_without_a_raw_source_commits_a_synthesis(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    change_set = ChangeSet(
        summary="Saved a reviewed synthesis.",
        drafts=[
            _draft(
                path="syntheses/reviewed-answer",
                type=ConceptType.SYNTHESIS,
                title="Reviewed answer",
                body="# Reviewed answer\n\nA concise synthesis.\n",
            )
        ],
    )
    context = ChangeValidationContext(
        mode="synthesis",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
    )

    prepared = prepare_transaction(workspace, change_set, context, None, NOW)

    values = _manifest(prepared)
    assert values["raw_path"] is None
    assert values["raw_sha256"] is None
    assert not (prepared.transaction_dir / "raw-source").exists()

    commit_transaction(prepared)

    assert (workspace.wiki_dir / "syntheses/reviewed-answer.md").is_file()
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))


def test_commit_rechecks_replacement_digest_before_any_persistence(tmp_path: Path) -> None:
    workspace, source, change_set, context = _ingestion(tmp_path)
    topic_path = workspace.wiki_dir / "topics/existing.md"
    topic_path.write_text(
        "---\n"
        "type: Topic\n"
        "title: Existing\n"
        "description: Existing knowledge.\n"
        "tags: []\n"
        "---\n\n"
        "# Existing\n",
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    existing = context.repository.get("topics/existing")
    replacement = _draft(
        operation=ChangeOperation.REPLACE,
        path="topics/existing",
        type=ConceptType.TOPIC,
        title="Updated",
        body="# Updated\n",
        base_digest=existing.digest,
    )
    change_set = change_set.model_copy(update={"drafts": [*change_set.drafts, replacement]})
    prepared = prepare_transaction(workspace, change_set, context, source, NOW)
    topic_path.write_text(
        topic_path.read_text(encoding="utf-8") + "external edit\n",
        encoding="utf-8",
    )

    with pytest.raises(TransactionError, match="stale"):
        commit_transaction(prepared)

    assert not (workspace.root / source.stored_relative_path).exists()
    assert "external edit" in topic_path.read_text(encoding="utf-8")


def test_commit_rejects_an_unrelated_live_edit_after_review(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    unrelated = prepared.workspace.wiki_dir / "topics/unrelated.md"
    unrelated.write_text(
        "---\n"
        "type: Topic\n"
        "title: Unrelated\n"
        "description: A concurrent knowledge edit.\n"
        "tags: []\n"
        "---\n\n"
        "# Unrelated\n",
        encoding="utf-8",
    )
    regenerate_indexes(prepared.workspace.wiki_dir)

    with pytest.raises(TransactionError, match="changed since preparation"):
        commit_transaction(prepared)

    assert unrelated.is_file()
    assert not (prepared.workspace.root / source.stored_relative_path).exists()


def test_commit_rejects_a_manifest_raw_path_that_differs_from_the_source(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    values = _manifest(prepared)
    values["raw_path"] = "raw/unreviewed.txt"
    (prepared.transaction_dir / "manifest.json").write_text(
        json.dumps(values),
        encoding="utf-8",
    )

    with pytest.raises(TransactionError, match="raw path"):
        commit_transaction(prepared)

    assert not (prepared.workspace.raw_dir / "unreviewed.txt").exists()


def test_commit_does_not_enter_swapping_when_the_backup_path_is_occupied(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    prepared.backup_wiki.mkdir()
    (prepared.backup_wiki / "unexpected.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="backup already exists"):
        commit_transaction(prepared)

    assert _manifest(prepared)["phase"] == "prepared"
    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki


@pytest.mark.parametrize(
    ("state", "expected_tree"),
    [
        ("prepared", "old"),
        ("raw-persisted", "old"),
        ("swapping-before-renames", "old"),
        ("swapping-after-old", "old"),
        ("swapping-after-new", "new"),
        ("new-live", "new"),
    ],
)
def test_recovery_at_each_phase_boundary_is_complete_and_idempotent(
    tmp_path: Path,
    state: str,
    expected_tree: str,
) -> None:
    prepared, source = _prepare(tmp_path)
    workspace = prepared.workspace
    old_tree = _tree_bytes(workspace.wiki_dir)
    new_tree = _tree_bytes(prepared.prospective_wiki)

    if state != "prepared":
        _persist_raw(prepared, source)
    if state == "raw-persisted":
        _set_phase(prepared, "raw-persisted")
    elif state.startswith("swapping"):
        _set_phase(prepared, "swapping")
    elif state == "new-live":
        _set_phase(prepared, "new-live")

    if state in {"swapping-after-old", "swapping-after-new", "new-live"}:
        workspace.wiki_dir.rename(prepared.backup_wiki)
    if state in {"swapping-after-new", "new-live"}:
        prepared.prospective_wiki.rename(workspace.wiki_dir)

    recover_transactions(workspace)
    recovered = _tree_bytes(workspace.wiki_dir)

    assert recovered == (old_tree if expected_tree == "old" else new_tree)
    assert recovered in [old_tree, new_tree]
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))
    assert not prepared.transaction_dir.exists()

    recover_transactions(workspace)
    assert _tree_bytes(workspace.wiki_dir) == recovered


def test_new_live_recovery_restores_the_backup_when_the_new_tree_is_invalid(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    _persist_raw(prepared, source)
    _set_phase(prepared, "new-live")
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)
    prepared.prospective_wiki.rename(prepared.workspace.wiki_dir)
    (prepared.workspace.wiki_dir / "index.md").write_text("corrupt\n", encoding="utf-8")

    recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == old_tree
    assert not prepared.transaction_dir.exists()


def test_recovery_restores_a_backup_when_the_manifest_is_incomplete(tmp_path: Path) -> None:
    prepared, _ = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)
    (prepared.transaction_dir / "manifest.json").unlink()

    recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == old_tree
    assert not prepared.transaction_dir.exists()


def test_recovery_rejects_manifest_paths_outside_the_workspace(tmp_path: Path) -> None:
    prepared, _ = _prepare(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")
    values = _manifest(prepared)
    values["prospective_path"] = "../outside"
    (prepared.transaction_dir / "manifest.json").write_text(
        json.dumps(values),
        encoding="utf-8",
    )

    with pytest.raises(TransactionError, match="safe workspace-relative"):
        recover_transactions(prepared.workspace)

    assert sentinel.read_text(encoding="utf-8") == "keep me\n"
    assert prepared.workspace.wiki_dir.is_dir()


def test_commit_rejects_an_existing_raw_file_with_different_bytes(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    destination = prepared.workspace.root / source.stored_relative_path
    destination.write_bytes(b"different bytes\n")

    with pytest.raises(TransactionError, match="different digest"):
        commit_transaction(prepared)

    assert destination.read_bytes() == b"different bytes\n"
    assert hashlib.sha256(destination.read_bytes()).hexdigest() != source.sha256


def test_manifest_update_does_not_follow_a_planted_fixed_temp_symlink(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("outside stays unchanged\n", encoding="utf-8")
    planted_temp = prepared.transaction_dir / "manifest.json.tmp"
    planted_temp.symlink_to(sentinel)

    commit_transaction(prepared)

    assert sentinel.read_text(encoding="utf-8") == "outside stays unchanged\n"


@pytest.mark.parametrize("phase", ["prepared", "raw-persisted"])
def test_early_phase_recovery_restores_the_only_wiki_copy(
    tmp_path: Path,
    phase: str,
) -> None:
    prepared, source = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    if phase == "raw-persisted":
        _persist_raw(prepared, source)
    _set_phase(prepared, phase)
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)

    recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == old_tree
    assert not prepared.transaction_dir.exists()


def test_prepare_fsyncs_the_transactions_parent_after_directory_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source, change_set, context = _ingestion(tmp_path)
    transactions_root = workspace.root / ".bundlewalker" / "transactions"
    observations: list[bool] = []
    original_sync = transactions._sync_directory  # pyright: ignore[reportPrivateUsage]

    def recording_sync(path: Path) -> None:
        if path == transactions_root:
            observations.append(any(path.iterdir()))
        original_sync(path)

    monkeypatch.setattr(transactions, "_sync_directory", recording_sync)

    prepared = prepare_transaction(workspace, change_set, context, source, NOW)

    assert prepared.transaction_dir.is_dir()
    assert True in observations


def test_commit_recursively_syncs_trees_before_each_swap_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    events: list[tuple[str, Path]] = []
    original_rename = Path.rename

    def recording_sync_tree(path: Path) -> None:
        events.append(("sync-tree", path))

    def recording_rename(path: Path, target: Path) -> Path:
        events.append(("rename", path))
        return original_rename(path, target)

    monkeypatch.setattr(transactions, "_sync_tree", recording_sync_tree, raising=False)
    monkeypatch.setattr(Path, "rename", recording_rename)

    commit_transaction(prepared)

    prospective_sync = events.index(("sync-tree", prepared.prospective_wiki))
    old_rename = events.index(("rename", prepared.workspace.wiki_dir))
    backup_sync = events.index(("sync-tree", prepared.backup_wiki))
    new_rename = events.index(("rename", prepared.prospective_wiki))
    live_sync = events.index(("sync-tree", prepared.workspace.wiki_dir))
    assert prospective_sync < old_rename < backup_sync < new_rename < live_sync


def test_commit_rejects_joint_manifest_and_prospective_tree_tampering(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    reviewed_digest = prepared.prospective_digest
    source_concept = next(prepared.prospective_wiki.glob("sources/*.md"))
    source_concept.write_text(
        source_concept.read_text(encoding="utf-8") + "\nTampered after review.\n",
        encoding="utf-8",
    )
    values = _manifest(prepared)
    values["prospective_digest"] = _transaction_tree_digest(prepared.prospective_wiki)
    (prepared.transaction_dir / "manifest.json").write_text(
        json.dumps(values),
        encoding="utf-8",
    )

    with pytest.raises(TransactionError, match="reviewed prospective"):
        commit_transaction(prepared)

    assert prepared.prospective_digest == reviewed_digest
    assert prepared.raw_source is not None
    assert not (prepared.workspace.wiki_dir / f"{prepared.raw_source.concept_id}.md").exists()


@pytest.mark.parametrize("manifest_present", [True, False])
def test_recovery_refuses_a_lint_valid_backup_with_the_wrong_identity(
    tmp_path: Path,
    manifest_present: bool,
) -> None:
    prepared, source = _prepare(tmp_path)
    _persist_raw(prepared, source)
    _set_phase(prepared, "new-live")
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)
    prepared.prospective_wiki.rename(prepared.workspace.wiki_dir)
    (prepared.workspace.wiki_dir / "index.md").write_text("corrupt\n", encoding="utf-8")
    tampered = prepared.backup_wiki / "topics/tampered-backup.md"
    tampered.write_text(
        "---\n"
        "type: Topic\n"
        "title: Tampered backup\n"
        "description: Lint-valid but not the reviewed base.\n"
        "tags: []\n"
        "---\n\n"
        "# Tampered backup\n",
        encoding="utf-8",
    )
    regenerate_indexes(prepared.backup_wiki)
    if not manifest_present:
        (prepared.transaction_dir / "manifest.json").unlink()

    with pytest.raises(TransactionError, match=r"backup.*identity"):
        recover_transactions(prepared.workspace)

    assert prepared.backup_wiki.is_dir()
    assert tampered.is_file()


def test_concurrent_edit_after_live_rename_is_restored_and_commit_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    original_rename = Path.rename
    injected = False

    def rename_with_concurrent_edit(path: Path, target: Path) -> Path:
        nonlocal injected
        result = original_rename(path, target)
        if path == prepared.workspace.wiki_dir and target == prepared.backup_wiki and not injected:
            injected = True
            concurrent = prepared.backup_wiki / "topics/concurrent.md"
            concurrent.write_text(
                "---\n"
                "type: Topic\n"
                "title: Concurrent\n"
                "description: A concurrent live edit.\n"
                "tags: []\n"
                "---\n\n"
                "# Concurrent\n",
                encoding="utf-8",
            )
            regenerate_indexes(prepared.backup_wiki)
        return result

    monkeypatch.setattr(Path, "rename", rename_with_concurrent_edit)

    with pytest.raises(TransactionError, match="changed during swap"):
        commit_transaction(prepared)

    assert (prepared.workspace.wiki_dir / "topics/concurrent.md").is_file()
    assert not prepared.transaction_dir.exists()


def test_concurrent_edit_before_backup_deletion_is_restored_and_commit_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    original_rename = Path.rename
    injected = False

    def rename_with_late_concurrent_edit(path: Path, target: Path) -> Path:
        nonlocal injected
        result = original_rename(path, target)
        if path == prepared.prospective_wiki and target == prepared.workspace.wiki_dir:
            injected = True
            concurrent = prepared.backup_wiki / "topics/late-concurrent.md"
            concurrent.write_text(
                "---\n"
                "type: Topic\n"
                "title: Late concurrent\n"
                "description: An edit during the final swap window.\n"
                "tags: []\n"
                "---\n\n"
                "# Late concurrent\n",
                encoding="utf-8",
            )
            regenerate_indexes(prepared.backup_wiki)
        return result

    monkeypatch.setattr(Path, "rename", rename_with_late_concurrent_edit)

    with pytest.raises(TransactionError, match="changed during swap"):
        commit_transaction(prepared)

    assert injected
    assert (prepared.workspace.wiki_dir / "topics/late-concurrent.md").is_file()
    assert not prepared.transaction_dir.exists()


def test_transaction_error_during_swap_recovers_a_valid_live_wiki(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    original_sync = transactions._sync_directory  # pyright: ignore[reportPrivateUsage]
    failed = False

    def fail_once_after_old_rename(path: Path) -> None:
        nonlocal failed
        if (
            not failed
            and prepared.backup_wiki.is_dir()
            and not prepared.workspace.wiki_dir.exists()
        ):
            failed = True
            raise TransactionError("injected directory fsync failure")
        original_sync(path)

    monkeypatch.setattr(transactions, "_sync_directory", fail_once_after_old_rename)

    with pytest.raises(TransactionError, match="injected directory fsync failure"):
        commit_transaction(prepared)

    assert _tree_bytes(prepared.workspace.wiki_dir) == old_tree
    assert not prepared.transaction_dir.exists()


def test_parent_fsync_failure_after_cleanup_recognizes_the_valid_live_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    new_tree = _tree_bytes(prepared.prospective_wiki)
    original_sync = transactions._sync_directory  # pyright: ignore[reportPrivateUsage]
    failed = False

    def fail_once_after_cleanup(path: Path) -> None:
        nonlocal failed
        if (
            not failed
            and path == prepared.transaction_dir.parent
            and not prepared.transaction_dir.exists()
        ):
            failed = True
            raise TransactionError("injected parent fsync failure")
        original_sync(path)

    monkeypatch.setattr(transactions, "_sync_directory", fail_once_after_cleanup)

    with pytest.raises(TransactionError, match="filesystem state was recovered"):
        commit_transaction(prepared)

    assert failed
    assert _tree_bytes(prepared.workspace.wiki_dir) == new_tree
    assert not prepared.transaction_dir.exists()


def test_corrupt_prospective_staging_does_not_block_exact_backup_recovery(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    _set_phase(prepared, "swapping")
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (prepared.prospective_wiki / "unsafe-link").symlink_to(outside)

    recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == old_tree
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_commit_rejects_a_configured_raw_directory_symlink_inside_workspace(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    redirect = prepared.workspace.root / "redirect"
    redirect.mkdir()
    prepared.workspace.raw_dir.rmdir()
    prepared.workspace.raw_dir.symlink_to(redirect, target_is_directory=True)

    with pytest.raises(TransactionError, match=r"raw.*symlink"):
        commit_transaction(prepared)

    assert not (redirect / source.stored_relative_path.name).exists()


def test_uuid_collision_does_not_delete_an_unowned_transaction_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source, change_set, context = _ingestion(tmp_path)
    fixed_uuid = uuid.UUID(int=1)
    collision = workspace.root / ".bundlewalker" / "transactions" / fixed_uuid.hex
    collision.mkdir(parents=True)
    sentinel = collision / "sentinel.txt"
    sentinel.write_text("pre-existing\n", encoding="utf-8")

    def return_fixed_uuid() -> uuid.UUID:
        return fixed_uuid

    monkeypatch.setattr(transactions.uuid, "uuid4", return_fixed_uuid)

    with pytest.raises(TransactionError, match="prepare transaction"):
        prepare_transaction(workspace, change_set, context, source, NOW)

    assert sentinel.read_text(encoding="utf-8") == "pre-existing\n"
