# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
import os
import shutil
import uuid
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
from bundlewalker.errors import (
    ReviewMismatchError,
    ReviewNotFoundError,
    ReviewPendingError,
    ReviewStaleError,
    TransactionError,
)
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    ReviewStatus,
    apply_pending_review,
    commit_transaction,
    discard_pending_review,
    discard_transaction,
    ensure_no_pending_review,
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
        kind=ReviewKind.INGESTION,
    )
    return prepared, source


def _prepare_in_workspace(
    workspace: Workspace,
    input_path: Path,
) -> tuple[PreparedTransaction, RawSource]:
    source, change_set, context = _ingestion_in_workspace(input_path.parent, workspace)
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    return prepared, source


def _ingestion_in_workspace(
    tmp_path: Path,
    workspace: Workspace,
) -> tuple[RawSource, ChangeSet, ChangeValidationContext]:
    input_path = tmp_path / "Nested Source Notes.txt"
    input_path.write_bytes(b"first line\nsecond line\n")
    source = load_raw_source(input_path, workspace)
    change_set = ChangeSet(
        summary="Integrated nested source notes.",
        source_sha256=source.sha256,
        drafts=[
            _draft(
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Nested source notes",
                body="# Nested source notes\n\nA grounded claim [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=2,
                    )
                ],
            )
        ],
    )
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    return source, change_set, context


def _nested_workspace(
    tmp_path: Path,
    *,
    nested_wiki: bool = False,
    nested_raw: bool = False,
) -> Workspace:
    workspace = initialize_workspace(tmp_path / "nested-knowledge", occurred_at=NOW)
    configured = workspace.root / "configured"
    configured.mkdir()
    config = workspace.config
    if nested_wiki:
        workspace.wiki_dir.rename(configured / "wiki")
        config = replace(config, wiki_dir="configured/wiki")
    if nested_raw:
        workspace.raw_dir.rename(configured / "raw")
        config = replace(config, raw_dir="configured/raw")
    (workspace.root / "bundlewalker.toml").write_text(
        "version = 1\n"
        f'wiki_dir = "{config.wiki_dir}"\n'
        f'raw_dir = "{config.raw_dir}"\n'
        f'conventions_file = "{config.conventions_file}"\n'
        f"max_source_characters = {config.max_source_characters}\n",
        encoding="utf-8",
    )
    return Workspace(root=workspace.root, config=config)


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


def _set_legacy_schema(prepared: PreparedTransaction) -> None:
    manifest_path = prepared.transaction_dir / "manifest.json"
    manifest = _manifest(prepared)
    manifest["schema_version"] = 1
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identity_path = prepared.transaction_dir / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity.pop("review_digest")
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (prepared.transaction_dir / "review.json").unlink()


def _persist_raw(prepared: PreparedTransaction, source: RawSource) -> None:
    destination = prepared.workspace.root / source.stored_relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.content)


def _concurrent_prepare_worker(
    workspace_root: str,
    source_directory: str,
    barrier: Any,
    results: Any,
) -> None:
    workspace = discover_workspace(Path(workspace_root))
    source, change_set, context = _ingestion_in_workspace(Path(source_directory), workspace)
    barrier.wait(timeout=10)
    try:
        prepared = prepare_transaction(
            workspace,
            change_set,
            context,
            source,
            NOW,
            kind=ReviewKind.INGESTION,
        )
    except ReviewPendingError as error:
        results.put(("pending", error.review_id))
    except BaseException as error:
        results.put(("error", f"{type(error).__name__}: {error}"))
    else:
        results.put(("prepared", prepared.transaction_id))


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
        kind=ReviewKind.INGESTION,
    )

    added_files = set(_tree_bytes(workspace.root)) - files_before
    transaction_prefix = f".bundlewalker/transactions/{prepared.transaction_id}/"
    assert added_files
    assert all(
        path.startswith(transaction_prefix) or path == ".bundlewalker/transaction.lock"
        for path in added_files
    )
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
    assert values["schema_version"] == 2
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


def test_prepare_persists_exact_review_record_and_identity(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    review_path = prepared.transaction_dir / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    identity = json.loads((prepared.transaction_dir / "identity.json").read_text(encoding="utf-8"))

    assert review == {
        "changed_paths": [prepared.change_set.drafts[0].path],
        "created_at": NOW.isoformat(),
        "diff": prepared.diff,
        "kind": "ingestion",
        "schema_version": 1,
        "summary": prepared.summary,
        "transaction_id": prepared.transaction_id,
    }
    assert identity["review_digest"] == hashlib.sha256(review_path.read_bytes()).hexdigest()


def test_load_review_authenticates_the_same_bytes_it_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _source = _prepare(tmp_path)
    review_path = prepared.transaction_dir / "review.json"
    expected_digest = hashlib.sha256(review_path.read_bytes()).hexdigest()
    original_read_text = Path.read_text

    def replace_after_text_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        content = original_read_text(
            path,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )
        if path == review_path:
            path.write_text('{"replacement": true}\n', encoding="utf-8")
        return content

    monkeypatch.setattr(Path, "read_text", replace_after_text_read)

    review = transactions._load_review(  # pyright: ignore[reportPrivateUsage]
        prepared.transaction_dir,
        expected_digest,
    )

    assert review.transaction_id == prepared.transaction_id


def test_recovery_preserves_schema_v2_pending_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    recover_transactions(prepared.workspace)
    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.status is ReviewStatus.PENDING
    assert loaded.diff == prepared.diff


def test_pending_review_becomes_stale_after_live_edit(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    (prepared.workspace.wiki_dir / "external.md").write_text(
        "external\n",
        encoding="utf-8",
    )

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.status is ReviewStatus.STALE


def test_loaded_review_can_apply_without_original_handle(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    review_id = prepared.transaction_id
    workspace = prepared.workspace
    del prepared

    apply_pending_review(workspace, review_id)

    assert get_pending_review(workspace) is None
    assert (workspace.root / source.stored_relative_path).read_bytes() == source.content


def test_wrong_review_id_cannot_resolve_current_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    with pytest.raises(
        ReviewMismatchError,
        match=r"^review ID does not match the pending review$",
    ):
        discard_pending_review(prepared.workspace, "0" * 32)

    loaded = get_pending_review(prepared.workspace)
    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id


def test_malformed_review_id_is_rejected_without_inspecting_a_named_path(
    tmp_path: Path,
) -> None:
    prepared, _source = _prepare(tmp_path)

    with pytest.raises(
        ReviewMismatchError,
        match=r"^review ID does not match the pending review$",
    ):
        apply_pending_review(prepared.workspace, "../manifest.json")

    assert prepared.transaction_dir.is_dir()


@pytest.mark.parametrize("review_id", [None, 17, b"0" * 32])
def test_non_string_review_id_uses_fixed_mismatch_error(
    tmp_path: Path,
    review_id: object,
) -> None:
    prepared, _source = _prepare(tmp_path)

    with pytest.raises(
        ReviewMismatchError,
        match=r"^review ID does not match the pending review$",
    ):
        apply_pending_review(
            prepared.workspace,
            review_id,  # pyright: ignore[reportArgumentType]
        )

    assert prepared.transaction_dir.is_dir()


def test_missing_pending_review_raises_not_found(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    with pytest.raises(ReviewNotFoundError):
        apply_pending_review(workspace, "0" * 32)


def test_stale_review_cannot_apply_but_can_discard(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    (prepared.workspace.wiki_dir / "external.md").write_text(
        "external\n",
        encoding="utf-8",
    )

    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, prepared.transaction_id)
    discard_pending_review(prepared.workspace, prepared.transaction_id)

    assert get_pending_review(prepared.workspace) is None


def test_missing_live_wiki_preserves_pending_review_as_stale(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    shutil.rmtree(prepared.workspace.wiki_dir)

    recover_transactions(prepared.workspace)
    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.status is ReviewStatus.STALE
    assert prepared.transaction_dir.is_dir()


def test_second_preparation_is_rejected_without_removing_first(tmp_path: Path) -> None:
    first, _source = _prepare(tmp_path)

    with pytest.raises(ReviewPendingError) as ensured:
        ensure_no_pending_review(first.workspace)
    with pytest.raises(ReviewPendingError) as raised:
        _prepare_in_workspace(first.workspace, tmp_path / "other.txt")

    assert ensured.value.review_id == first.transaction_id
    assert raised.value.review_id == first.transaction_id
    loaded = get_pending_review(first.workspace)
    assert loaded is not None
    assert loaded.review_id == first.transaction_id


def test_simultaneous_public_preparations_create_exactly_one_review(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    source_directories = [tmp_path / "worker-one", tmp_path / "worker-two"]
    for directory in source_directories:
        directory.mkdir()
    process_context = multiprocessing.get_context("spawn")
    barrier = process_context.Barrier(2)
    results = process_context.Queue()
    processes = [
        process_context.Process(
            target=_concurrent_prepare_worker,
            args=(str(workspace.root), str(directory), barrier, results),
        )
        for directory in source_directories
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        assert all(not process.is_alive() for process in processes)
        assert all(process.exitcode == 0 for process in processes)
        outcomes = [cast(tuple[str, str], results.get(timeout=2)) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
        results.close()
        results.join_thread()

    assert sorted(kind for kind, _review_id in outcomes) == ["pending", "prepared"]
    prepared_id = next(review_id for kind, review_id in outcomes if kind == "prepared")
    pending_id = next(review_id for kind, review_id in outcomes if kind == "pending")
    assert pending_id == prepared_id
    durable = get_pending_review(workspace)
    assert durable is not None
    assert durable.review_id == prepared_id
    transaction_dirs = [
        path
        for path in (workspace.root / ".bundlewalker" / "transactions").iterdir()
        if path.is_dir()
    ]
    assert [path.name for path in transaction_dirs] == [prepared_id]


def test_recovery_rejects_more_than_one_valid_pending_review(tmp_path: Path) -> None:
    first, _source = _prepare(tmp_path)
    source, change_set, context = _ingestion_in_workspace(tmp_path, first.workspace)
    transactions._prepare_transaction_locked(  # pyright: ignore[reportPrivateUsage]
        first.workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
        transactions_root=first.transaction_dir.parent,
    )

    with pytest.raises(TransactionError, match="more than one pending review"):
        recover_transactions(first.workspace)


def test_corrupted_review_record_is_not_loadable(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    review_path = prepared.transaction_dir / "review.json"
    review_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="review identity"):
        get_pending_review(prepared.workspace)


def test_recovery_cleans_legacy_schema_v1_prepared_transaction(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    _set_legacy_schema(prepared)

    recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki
    assert not prepared.transaction_dir.exists()


def test_schema_v2_pending_recovery_rejects_missing_prospective_and_retains_journal(
    tmp_path: Path,
) -> None:
    prepared, _source = _prepare(tmp_path)
    shutil.rmtree(prepared.prospective_wiki)

    with pytest.raises(TransactionError, match="prospective"):
        get_pending_review(prepared.workspace)

    assert prepared.transaction_dir.is_dir()
    assert _manifest(prepared)["phase"] == "prepared"


def test_schema_v2_pending_recovery_rejects_unexpected_backup_and_retains_journal(
    tmp_path: Path,
) -> None:
    prepared, _source = _prepare(tmp_path)
    prepared.backup_wiki.mkdir()

    with pytest.raises(TransactionError, match="backup"):
        get_pending_review(prepared.workspace)

    assert prepared.transaction_dir.is_dir()
    assert prepared.backup_wiki.is_dir()
    assert _manifest(prepared)["phase"] == "prepared"


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


def test_commit_persists_accepted_before_raw_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _source = _prepare(tmp_path)
    observed_phases: list[object] = []
    original_persist = transactions._persist_raw_source  # pyright: ignore[reportPrivateUsage]

    def observe_persist(
        workspace: Workspace,
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        observed_phases.append(_manifest(prepared)["phase"])
        original_persist(workspace, transaction_dir, manifest)

    monkeypatch.setattr(transactions, "_persist_raw_source", observe_persist)

    commit_transaction(prepared)

    assert observed_phases == ["accepted"]


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

    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        None,
        NOW,
        kind=ReviewKind.SYNTHESIS,
    )

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
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
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
        ("raw-persisted", "new"),
        ("swapping-before-renames", "new"),
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


def test_accepted_recovery_blocks_corrupt_transaction_owned_tree(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    _set_phase(prepared, "accepted")
    (prepared.prospective_wiki / "index.md").write_text(
        "corrupt prospective bytes\n",
        encoding="utf-8",
    )

    with pytest.raises(TransactionError, match="reviewed tree"):
        recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki
    assert not (prepared.workspace.root / source.stored_relative_path).exists()
    assert prepared.transaction_dir.is_dir()


def test_accepted_recovery_blocks_when_raw_persistence_is_ambiguous(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    _set_phase(prepared, "accepted")
    manifest = transactions._load_manifest(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
    )
    transactions._persist_raw_source(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
        manifest,
    )
    external = prepared.workspace.wiki_dir / "external.md"
    external.write_text("external live bytes\n", encoding="utf-8")
    live_after_external_edit = _tree_bytes(prepared.workspace.wiki_dir)

    with pytest.raises(TransactionError, match="raw persistence is ambiguous"):
        recover_transactions(prepared.workspace)

    assert _tree_bytes(prepared.workspace.wiki_dir) == live_after_external_edit
    assert (prepared.workspace.root / source.stored_relative_path).read_bytes() == source.content
    assert prepared.transaction_dir.is_dir()


def test_accepted_raw_link_with_unreadable_identity_preserves_journal(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    _set_phase(prepared, "accepted")
    manifest = transactions._load_manifest(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
    )
    transactions._persist_raw_source(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
        manifest,
    )
    raw_path = prepared.workspace.root / source.stored_relative_path
    (prepared.transaction_dir / "identity.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="schema-v2 transaction identity"):
        recover_transactions(prepared.workspace)

    assert raw_path.read_bytes() == source.content
    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki
    assert prepared.transaction_dir.is_dir()


def test_accepted_raw_link_with_unreadable_manifest_preserves_journal(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    live_wiki = _tree_bytes(prepared.workspace.wiki_dir)
    _set_phase(prepared, "accepted")
    manifest = transactions._load_manifest(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
    )
    transactions._persist_raw_source(  # pyright: ignore[reportPrivateUsage]
        prepared.workspace,
        prepared.transaction_dir,
        manifest,
    )
    raw_path = prepared.workspace.root / source.stored_relative_path
    (prepared.transaction_dir / "manifest.json").write_text("{\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="schema-v2 transaction manifest"):
        recover_transactions(prepared.workspace)

    assert raw_path.read_bytes() == source.content
    assert _tree_bytes(prepared.workspace.wiki_dir) == live_wiki
    assert prepared.transaction_dir.is_dir()


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


def test_legacy_recovery_restores_a_backup_when_the_manifest_is_incomplete(
    tmp_path: Path,
) -> None:
    prepared, _ = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    _set_legacy_schema(prepared)
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


def test_conflicting_raw_destination_is_stale_and_remains_discardable(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    destination = prepared.workspace.root / source.stored_relative_path
    destination.write_bytes(b"conflicting bytes\n")

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.diff == prepared.diff
    assert loaded.status is ReviewStatus.STALE
    assert _manifest(prepared)["phase"] == "prepared"
    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, loaded.review_id)
    discard_pending_review(prepared.workspace, loaded.review_id)
    assert destination.read_bytes() == b"conflicting bytes\n"
    assert not prepared.transaction_dir.exists()


def test_raw_destination_symlink_is_stale_and_remains_discardable(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    outside = tmp_path / "outside-raw.txt"
    outside.write_bytes(source.content)
    destination = prepared.workspace.root / source.stored_relative_path
    destination.symlink_to(outside)

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.diff == prepared.diff
    assert loaded.status is ReviewStatus.STALE
    assert _manifest(prepared)["phase"] == "prepared"
    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, loaded.review_id)
    discard_pending_review(prepared.workspace, loaded.review_id)
    assert destination.is_symlink()
    assert outside.read_bytes() == source.content
    assert not prepared.transaction_dir.exists()


def test_missing_raw_parent_is_stale_and_remains_discardable(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    prepared.workspace.raw_dir.rmdir()

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.diff == prepared.diff
    assert loaded.status is ReviewStatus.STALE
    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, loaded.review_id)
    discard_pending_review(prepared.workspace, loaded.review_id)
    assert not prepared.workspace.raw_dir.exists()
    assert not prepared.transaction_dir.exists()


def test_linked_raw_parent_is_stale_and_remains_discardable(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    prepared.workspace.raw_dir.rmdir()
    outside = tmp_path / "outside-raw"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"external bytes\n")
    prepared.workspace.raw_dir.symlink_to(outside, target_is_directory=True)

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.diff == prepared.diff
    assert loaded.status is ReviewStatus.STALE
    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, loaded.review_id)
    discard_pending_review(prepared.workspace, loaded.review_id)
    assert prepared.workspace.raw_dir.is_symlink()
    assert sentinel.read_bytes() == b"external bytes\n"
    assert not prepared.transaction_dir.exists()


def test_apply_revalidates_raw_destination_changed_after_status_before_acceptance(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    destination = prepared.workspace.root / source.stored_relative_path
    destination.write_bytes(b"raced conflicting bytes\n")

    with pytest.raises(ReviewStaleError, match="pending review is stale"):
        apply_pending_review(prepared.workspace, pending.review_id)

    assert _manifest(prepared)["phase"] == "prepared"
    discard_pending_review(prepared.workspace, pending.review_id)
    assert destination.read_bytes() == b"raced conflicting bytes\n"


def test_final_raw_check_runs_after_live_checks_and_preserves_prepared_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, source = _prepare(tmp_path)
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    destination = prepared.workspace.root / source.stored_relative_path
    events: list[str] = []
    original_verify_live = transactions._verify_live_base  # pyright: ignore[reportPrivateUsage]
    original_require_raw = transactions._require_compatible_raw_destination  # pyright: ignore[reportPrivateUsage]

    def observe_live_check(
        workspace: Workspace,
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        events.append("live-base")
        original_verify_live(workspace, transaction_dir, manifest)

    def inject_at_final_raw_check(
        workspace: Workspace,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        events.append("raw-destination")
        destination.write_bytes(b"boundary conflicting bytes\n")
        original_require_raw(workspace, manifest)

    monkeypatch.setattr(transactions, "_verify_live_base", observe_live_check)
    monkeypatch.setattr(
        transactions,
        "_require_compatible_raw_destination",
        inject_at_final_raw_check,
    )

    with pytest.raises(ReviewStaleError, match="raw destination"):
        apply_pending_review(prepared.workspace, pending.review_id)

    assert events == ["live-base", "raw-destination"]
    assert _manifest(prepared)["phase"] == "prepared"
    assert destination.read_bytes() == b"boundary conflicting bytes\n"


def test_raw_conflict_after_accepted_rolls_back_to_stale_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, source = _prepare(tmp_path)
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    destination = prepared.workspace.root / source.stored_relative_path
    original_persist = transactions._persist_raw_source  # pyright: ignore[reportPrivateUsage]

    def race_after_acceptance(
        workspace: Workspace,
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        assert manifest.phase == "accepted"
        assert _manifest(prepared)["phase"] == "accepted"
        destination.write_bytes(b"post-accept conflicting bytes\n")
        original_persist(workspace, transaction_dir, manifest)

    monkeypatch.setattr(transactions, "_persist_raw_source", race_after_acceptance)

    with pytest.raises(ReviewStaleError, match="raw destination"):
        apply_pending_review(prepared.workspace, pending.review_id)

    assert _manifest(prepared)["phase"] == "prepared"
    loaded = get_pending_review(discover_workspace(prepared.workspace.root))
    assert loaded is not None
    assert loaded.review_id == pending.review_id
    assert loaded.diff == pending.diff
    assert loaded.status is ReviewStatus.STALE
    discard_pending_review(prepared.workspace, loaded.review_id)
    assert destination.read_bytes() == b"post-accept conflicting bytes\n"
    assert not prepared.transaction_dir.exists()


def test_accepted_restart_with_raw_conflict_recovers_stale_review(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    destination = prepared.workspace.root / source.stored_relative_path
    _set_phase(prepared, "accepted")
    destination.write_bytes(b"restart conflicting bytes\n")

    restarted = discover_workspace(prepared.workspace.root)
    loaded = get_pending_review(restarted)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.diff == prepared.diff
    assert loaded.status is ReviewStatus.STALE
    assert _manifest(prepared)["phase"] == "prepared"
    with pytest.raises(ReviewStaleError):
        apply_pending_review(restarted, loaded.review_id)
    discard_pending_review(restarted, loaded.review_id)
    assert destination.read_bytes() == b"restart conflicting bytes\n"
    assert not prepared.transaction_dir.exists()


def test_accepted_raw_conflict_with_corrupt_payload_remains_fail_closed(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    destination = prepared.workspace.root / source.stored_relative_path
    _set_phase(prepared, "accepted")
    destination.write_bytes(b"external conflicting bytes\n")
    (prepared.transaction_dir / "raw-source").write_bytes(b"corrupt staged bytes\n")

    with pytest.raises(TransactionError, match="raw payload has a different digest"):
        get_pending_review(discover_workspace(prepared.workspace.root))

    assert _manifest(prepared)["phase"] == "accepted"
    assert destination.read_bytes() == b"external conflicting bytes\n"
    with pytest.raises(TransactionError):
        discard_pending_review(prepared.workspace, prepared.transaction_id)
    assert prepared.transaction_dir.is_dir()


def test_accepted_raw_conflict_with_backup_remains_fail_closed(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    destination = prepared.workspace.root / source.stored_relative_path
    _set_phase(prepared, "accepted")
    destination.write_bytes(b"external conflicting bytes\n")
    prepared.backup_wiki.mkdir()

    with pytest.raises(TransactionError, match="unexpectedly contains a backup"):
        get_pending_review(discover_workspace(prepared.workspace.root))

    assert _manifest(prepared)["phase"] == "accepted"
    assert destination.read_bytes() == b"external conflicting bytes\n"
    with pytest.raises(TransactionError):
        discard_pending_review(prepared.workspace, prepared.transaction_id)
    assert prepared.transaction_dir.is_dir()


def test_link_then_raw_parent_move_retains_accepted_journal_and_parked_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, source = _prepare(tmp_path)
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    payload = prepared.transaction_dir / "raw-source"
    destination = prepared.workspace.root / source.stored_relative_path
    parked_raw = prepared.workspace.root / "parked-raw"
    original_link = os.link

    def link_then_move_parent(*args: object, **kwargs: object) -> None:
        original_link(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        prepared.workspace.raw_dir.rename(parked_raw)

    monkeypatch.setattr(transactions.os, "link", link_then_move_parent)

    with pytest.raises(TransactionError):
        apply_pending_review(prepared.workspace, pending.review_id)

    parked_destination = parked_raw / destination.name
    payload_stat = payload.stat()
    parked_stat = parked_destination.stat()
    assert (parked_stat.st_dev, parked_stat.st_ino) == (
        payload_stat.st_dev,
        payload_stat.st_ino,
    )
    assert payload_stat.st_nlink >= 2
    assert _manifest(prepared)["phase"] == "accepted"
    with pytest.raises(TransactionError):
        get_pending_review(discover_workspace(prepared.workspace.root))
    with pytest.raises(TransactionError):
        discard_pending_review(prepared.workspace, pending.review_id)
    assert parked_destination.read_bytes() == source.content
    assert prepared.transaction_dir.is_dir()


def test_link_then_exact_parent_replacement_retains_accepted_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, source = _prepare(tmp_path)
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    payload = prepared.transaction_dir / "raw-source"
    destination = prepared.workspace.root / source.stored_relative_path
    parked_raw = prepared.workspace.root / "parked-raw"
    original_link = os.link

    def link_then_replace_parent(*args: object, **kwargs: object) -> None:
        original_link(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        prepared.workspace.raw_dir.rename(parked_raw)
        prepared.workspace.raw_dir.mkdir()
        destination.write_bytes(source.content)

    monkeypatch.setattr(transactions.os, "link", link_then_replace_parent)

    with pytest.raises(TransactionError):
        apply_pending_review(prepared.workspace, pending.review_id)

    parked_destination = parked_raw / destination.name
    payload_stat = payload.stat()
    parked_stat = parked_destination.stat()
    canonical_stat = destination.stat()
    assert (parked_stat.st_dev, parked_stat.st_ino) == (
        payload_stat.st_dev,
        payload_stat.st_ino,
    )
    assert (canonical_stat.st_dev, canonical_stat.st_ino) != (
        payload_stat.st_dev,
        payload_stat.st_ino,
    )
    assert destination.read_bytes() == source.content
    assert _manifest(prepared)["phase"] == "accepted"
    with pytest.raises(TransactionError):
        discard_pending_review(prepared.workspace, pending.review_id)
    assert parked_destination.read_bytes() == source.content
    assert prepared.transaction_dir.is_dir()


def test_accepted_restart_with_parked_payload_link_remains_fail_closed(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    payload = prepared.transaction_dir / "raw-source"
    destination = prepared.workspace.root / source.stored_relative_path
    parked_raw = prepared.workspace.root / "parked-raw"
    _set_phase(prepared, "accepted")
    os.link(payload, destination)
    prepared.workspace.raw_dir.rename(parked_raw)
    prepared.workspace.raw_dir.mkdir()

    with pytest.raises(TransactionError):
        get_pending_review(discover_workspace(prepared.workspace.root))

    parked_destination = parked_raw / destination.name
    payload_stat = payload.stat()
    parked_stat = parked_destination.stat()
    assert (parked_stat.st_dev, parked_stat.st_ino) == (
        payload_stat.st_dev,
        payload_stat.st_ino,
    )
    assert payload_stat.st_nlink >= 2
    assert _manifest(prepared)["phase"] == "accepted"
    with pytest.raises(TransactionError):
        discard_pending_review(prepared.workspace, prepared.transaction_id)
    assert prepared.transaction_dir.is_dir()


def test_accepted_restart_with_canonical_payload_link_resumes_commit(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    payload = prepared.transaction_dir / "raw-source"
    destination = prepared.workspace.root / source.stored_relative_path
    _set_phase(prepared, "accepted")
    os.link(payload, destination)

    recover_transactions(discover_workspace(prepared.workspace.root))

    assert destination.read_bytes() == source.content
    assert not prepared.transaction_dir.exists()


def test_exact_preexisting_raw_destination_is_compatible_with_pending_apply(
    tmp_path: Path,
) -> None:
    prepared, source = _prepare(tmp_path)
    payload = prepared.transaction_dir / "raw-source"
    destination = prepared.workspace.root / source.stored_relative_path
    destination.write_bytes(source.content)
    payload_identity = (payload.stat().st_dev, payload.stat().st_ino)
    destination_identity = (destination.stat().st_dev, destination.stat().st_ino)
    assert destination_identity != payload_identity

    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    apply_pending_review(prepared.workspace, pending.review_id)

    assert destination.read_bytes() == source.content
    assert (destination.stat().st_dev, destination.stat().st_ino) == destination_identity
    assert get_pending_review(prepared.workspace) is None


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


def test_raw_persisted_recovery_restores_the_only_wiki_copy(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    old_tree = _tree_bytes(prepared.workspace.wiki_dir)
    _persist_raw(prepared, source)
    _set_phase(prepared, "raw-persisted")
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

    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )

    assert prepared.transaction_dir.is_dir()
    assert True in observations


def test_commit_recursively_syncs_trees_before_each_swap_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    events: list[tuple[str, Path]] = []
    original_rename = transactions._rename_workspace_entry  # pyright: ignore[reportPrivateUsage]

    def recording_sync_tree(path: Path) -> None:
        events.append(("sync-tree", path))

    def recording_rename(workspace: Workspace, path: Path, target: Path) -> None:
        events.append(("rename", path))
        original_rename(workspace, path, target)

    monkeypatch.setattr(transactions, "_sync_tree", recording_sync_tree, raising=False)
    monkeypatch.setattr(transactions, "_rename_workspace_entry", recording_rename)

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

    expected_error = r"backup.*identity" if manifest_present else "schema-v2 transaction manifest"
    with pytest.raises(TransactionError, match=expected_error):
        recover_transactions(prepared.workspace)

    assert prepared.backup_wiki.is_dir()
    assert tampered.is_file()


def test_concurrent_edit_after_live_rename_is_restored_and_commit_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    original_rename = os.rename
    injected = False

    def rename_with_concurrent_edit(
        path: os.PathLike[str] | str,
        target: os.PathLike[str] | str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal injected
        original_rename(path, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if (
            os.fspath(path).endswith("wiki")
            and os.fspath(target).endswith("backup-wiki")
            and not injected
        ):
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

    monkeypatch.setattr(os, "rename", rename_with_concurrent_edit)

    with pytest.raises(TransactionError, match="changed during swap"):
        commit_transaction(prepared)

    assert (prepared.workspace.wiki_dir / "topics/concurrent.md").is_file()
    assert not prepared.transaction_dir.exists()


def test_concurrent_edit_before_backup_deletion_is_restored_and_commit_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    original_rename = os.rename
    injected = False

    def rename_with_late_concurrent_edit(
        path: os.PathLike[str] | str,
        target: os.PathLike[str] | str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal injected
        original_rename(path, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        if os.fspath(path).endswith("prospective-wiki") and os.fspath(target).endswith("wiki"):
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

    monkeypatch.setattr(os, "rename", rename_with_late_concurrent_edit)

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


def test_prepare_recovers_an_incomplete_transaction_before_allocating_its_id(
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

    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )

    assert prepared.transaction_id == fixed_uuid.hex
    assert not sentinel.exists()


def test_commit_rejects_a_linked_configured_wiki_ancestor_without_touching_outside(
    tmp_path: Path,
) -> None:
    workspace = _nested_workspace(tmp_path, nested_wiki=True)
    source, change_set, context = _ingestion_in_workspace(tmp_path, workspace)
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    outside = tmp_path / "outside-wiki-parent"
    outside.mkdir()
    shutil.copytree(workspace.wiki_dir, outside / "wiki")
    outside_before = _tree_bytes(outside)
    configured = workspace.root / "configured"
    configured.rename(workspace.root / "detached-configured")
    configured.symlink_to(outside, target_is_directory=True)

    with pytest.raises(TransactionError, match=r"wiki.*symlink|configured wiki"):
        commit_transaction(prepared)

    assert _tree_bytes(outside) == outside_before
    assert not (outside / "wiki" / f"{source.concept_id}.md").exists()


def test_raw_persistence_never_follows_an_intermediate_directory_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _nested_workspace(tmp_path, nested_raw=True)
    source, change_set, context = _ingestion_in_workspace(tmp_path, workspace)
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    outside = tmp_path / "outside-raw-parent"
    (outside / "raw").mkdir(parents=True)
    configured = workspace.root / "configured"
    parked = workspace.root / "configured-before-swap"
    injected = False
    original_open = os.open

    def inject_swap_once() -> None:
        nonlocal injected
        if injected:
            return
        injected = True
        configured.rename(parked)
        configured.symlink_to(outside, target_is_directory=True)

    def open_then_swap(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "configured" and dir_fd is not None:
            inject_swap_once()
        return descriptor

    monkeypatch.setattr(os, "open", open_then_swap)

    with pytest.raises(TransactionError):
        commit_transaction(prepared)

    assert injected
    assert not (outside / "raw" / source.stored_relative_path.name).exists()


def test_backup_change_immediately_after_final_digest_is_preserved_and_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    original_digest = transactions._materialized_tree_digest  # pyright: ignore[reportPrivateUsage]
    injected = False

    def digest_then_change(path: Path, transaction_dir: Path) -> str:
        nonlocal injected
        digest = original_digest(path, transaction_dir)
        if path == prepared.backup_wiki and prepared.workspace.wiki_dir.is_dir():
            concurrent = prepared.backup_wiki / "topics/after-final-digest.md"
            concurrent.write_text(
                "---\n"
                "type: Topic\n"
                "title: After final digest\n"
                "description: A concurrent edit at the cleanup boundary.\n"
                "tags: []\n"
                "---\n\n"
                "# After final digest\n",
                encoding="utf-8",
            )
            regenerate_indexes(prepared.backup_wiki)
            injected = True
        return digest

    monkeypatch.setattr(transactions, "_materialized_tree_digest", digest_then_change)

    with pytest.raises(TransactionError, match="changed during swap"):
        commit_transaction(prepared)

    assert injected
    assert (prepared.workspace.wiki_dir / "topics/after-final-digest.md").is_file()


def test_recovery_never_deletes_a_changed_quarantined_backup(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    _persist_raw(prepared, source)
    _set_phase(prepared, "new-live")
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)
    prepared.prospective_wiki.rename(prepared.workspace.wiki_dir)
    quarantine = prepared.transaction_dir / ".retired-backup-interrupted"
    prepared.backup_wiki.rename(quarantine)
    concurrent = quarantine / "topics/quarantined-concurrent.md"
    concurrent.write_text(
        "---\n"
        "type: Topic\n"
        "title: Quarantined concurrent\n"
        "description: Bytes written before interrupted cleanup.\n"
        "tags: []\n"
        "---\n\n"
        "# Quarantined concurrent\n",
        encoding="utf-8",
    )
    regenerate_indexes(quarantine)

    with pytest.raises(TransactionError, match=r"backup.*identity"):
        recover_transactions(prepared.workspace)

    assert concurrent.is_file()
    assert quarantine.is_dir()


def test_nested_wiki_commit_syncs_live_parent_after_each_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _nested_workspace(tmp_path, nested_wiki=True)
    source, change_set, context = _ingestion_in_workspace(tmp_path, workspace)
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    events: list[tuple[str, str, str | None]] = []
    original_rename = os.rename
    original_sync = transactions._sync_directory  # pyright: ignore[reportPrivateUsage]

    def recording_rename(
        source_path: os.PathLike[str] | str,
        target_path: os.PathLike[str] | str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        events.append(("rename", os.fspath(source_path), os.fspath(target_path)))
        original_rename(
            source_path,
            target_path,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def recording_sync(path: Path) -> None:
        events.append(("sync", os.fspath(path), None))
        original_sync(path)

    monkeypatch.setattr(os, "rename", recording_rename)
    monkeypatch.setattr(transactions, "_sync_directory", recording_sync)

    commit_transaction(prepared)

    old_rename = next(
        index
        for index, event in enumerate(events)
        if event[0] == "rename"
        and event[1].endswith("wiki")
        and event[2] is not None
        and event[2].endswith("backup-wiki")
    )
    new_rename = next(
        index
        for index, event in enumerate(events)
        if event[0] == "rename"
        and event[1].endswith("prospective-wiki")
        and event[2] is not None
        and event[2].endswith("wiki")
    )
    live_parent_syncs = [
        index
        for index, event in enumerate(events)
        if event == ("sync", os.fspath(workspace.wiki_dir.parent), None)
    ]
    assert any(old_rename < index < new_rename for index in live_parent_syncs)
    assert any(new_rename < index for index in live_parent_syncs)


def test_prepared_transaction_constructor_has_only_the_planned_fields() -> None:
    expected = (
        "transaction_id",
        "workspace",
        "transaction_dir",
        "prospective_wiki",
        "backup_wiki",
        "change_set",
        "raw_source",
        "summary",
        "diff",
    )

    assert tuple(inspect.signature(PreparedTransaction).parameters) == expected
    assert tuple(field.name for field in fields(PreparedTransaction) if field.init) == expected


def test_discard_syncs_the_transaction_parent_after_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _ = _prepare(tmp_path)
    observations: list[bool] = []
    original_sync = transactions._sync_directory  # pyright: ignore[reportPrivateUsage]

    def recording_sync(path: Path) -> None:
        if path == prepared.transaction_dir.parent:
            observations.append(prepared.transaction_dir.exists())
        original_sync(path)

    monkeypatch.setattr(transactions, "_sync_directory", recording_sync)

    discard_transaction(prepared)

    assert observations
    assert observations[-1] is False


def test_quiescent_workspace_yields_only_after_recovery(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    with transactions.quiescent_workspace(workspace) as quiescent:
        assert quiescent.workspace == workspace
        assert (workspace.root / ".bundlewalker/transaction.lock").is_file()


def test_quiescent_workspace_preserves_and_rejects_pending_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    with (
        pytest.raises(ReviewPendingError) as raised,
        transactions.quiescent_workspace(prepared.workspace),
    ):
        pytest.fail("pending review must prevent a quiescent snapshot")

    assert raised.value.review_id == prepared.transaction_id
    assert prepared.transaction_dir.is_dir()
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    assert pending.review_id == prepared.transaction_id
