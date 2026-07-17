from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bundlewalker.cli import app
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
runner = CliRunner()


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
