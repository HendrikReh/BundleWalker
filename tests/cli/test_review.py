# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bundlewalker.changes import ChangeValidationContext
from bundlewalker.cli import app
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    OkfMetadata,
)
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import ReviewKind, prepare_transaction
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace, load_inline_source

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
runner = CliRunner()


def _prepare_raw_review(workspace: Workspace) -> tuple[str, str, Path]:
    source = load_inline_source("notes.txt", "evidence\n", workspace)
    change_set = ChangeSet(
        summary="Integrated notes.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Notes",
                description="Evidence from notes.",
                tags=["notes"],
                body="# Notes\n\nEvidence [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=1,
                    )
                ],
            )
        ],
    )
    prepared = prepare_transaction(
        workspace,
        change_set,
        ChangeValidationContext(
            mode="ingest",
            repository=OkfRepository(workspace.wiki_dir),
            readable_concepts=frozenset(),
            source=source,
        ),
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    return (
        prepared.transaction_id,
        prepared.diff,
        workspace.root / source.stored_relative_path,
    )


@pytest.fixture
def cli_workspace_with_pending_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
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
    prepared = prepare_synthesis(
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
    monkeypatch.chdir(workspace.root)
    return workspace.root, prepared.transaction_id


def test_review_show_apply_survives_new_cli_invocation(
    cli_workspace_with_pending_review: tuple[Path, str],
) -> None:
    root, review_id = cli_workspace_with_pending_review

    shown = runner.invoke(app, ["review", "show"])
    applied = runner.invoke(app, ["review", "apply", review_id])

    assert shown.exit_code == 0
    assert review_id in shown.output
    assert "--- wiki/" in shown.output
    assert applied.exit_code == 0
    assert "Changes applied." in applied.output
    assert not list((root / ".bundlewalker" / "transactions").glob("*/manifest.json"))


def test_write_command_reports_existing_review_before_model(
    cli_workspace_with_pending_review: tuple[Path, str],
) -> None:
    _root, review_id = cli_workspace_with_pending_review

    result = runner.invoke(app, ["ask", "question", "--save", "--model", "test:model"])

    assert result.exit_code == 1
    assert review_id in result.output
    assert "bundlewalker review show" in result.output


def test_review_discard_removes_pending_review_without_live_changes(
    cli_workspace_with_pending_review: tuple[Path, str],
) -> None:
    root, review_id = cli_workspace_with_pending_review
    wiki_before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted((root / "wiki").rglob("*"))
        if path.is_file()
    }

    discarded = runner.invoke(app, ["review", "discard", review_id])

    assert discarded.exit_code == 0
    assert "No changes applied." in discarded.output
    assert wiki_before == {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted((root / "wiki").rglob("*"))
        if path.is_file()
    }
    assert not list((root / ".bundlewalker" / "transactions").glob("*/manifest.json"))


def test_raw_symlink_review_is_resolvable_across_fresh_cli_invocations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    review_id, diff, destination = _prepare_raw_review(workspace)
    outside = tmp_path / "outside-raw.txt"
    outside.write_bytes(b"external bytes\n")
    destination.symlink_to(outside)
    monkeypatch.chdir(workspace.root)

    shown = runner.invoke(app, ["review", "show"])
    applied = runner.invoke(app, ["review", "apply", review_id])
    discarded = runner.invoke(app, ["review", "discard", review_id])

    assert shown.exit_code == 0
    assert f"Review ID: {review_id}" in shown.output
    assert "Status: stale" in shown.output
    assert diff in shown.output
    assert applied.exit_code == 1
    assert "Error: review is stale" in applied.output
    assert discarded.exit_code == 0
    assert destination.is_symlink()
    assert outside.read_bytes() == b"external bytes\n"
    assert not list((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
