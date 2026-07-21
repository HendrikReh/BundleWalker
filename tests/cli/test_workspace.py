# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import bundlewalker.interfaces.cli as cli_module
from bundlewalker.application import LifecycleApplication, LifecycleDependencies
from bundlewalker.cli import app
from bundlewalker.compatibility import MigrationStep
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
runner = CliRunner()


def test_workspace_status_reports_future_format_without_creating_state(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text("version = 2\nfuture_path = 'future'\n", encoding="utf-8")

    result = runner.invoke(app, ["workspace", "status", str(root)])

    assert result.exit_code == 0, result.output
    assert result.output == (
        "BundleWalker version: 0.4.0rc1\n"
        f"Workspace: {root.resolve()}\n"
        "Workspace format: 2\n"
        "Compatibility: too_new\n"
        "Readable: no\n"
        "Writable: no\n"
        "Upgrade available: no\n"
    )
    assert list(root.iterdir()) == [config]
    assert not (root / ".bundlewalker").exists()


def test_workspace_backup_and_restore_work_outside_workspace_cwd(tmp_path: Path) -> None:
    source = initialize_workspace(tmp_path / "source", occurred_at=NOW)
    archive = tmp_path / "source.zip"
    target = tmp_path / "restored"

    backed_up = runner.invoke(
        app,
        ["workspace", "backup", str(archive), "--workspace", str(source.root)],
    )
    restored = runner.invoke(app, ["workspace", "restore", str(archive), str(target)])

    assert backed_up.exit_code == 0, backed_up.output
    assert restored.exit_code == 0, restored.output
    assert f"Backup: {archive.resolve()}" in backed_up.output
    assert "SHA-256:" in backed_up.output
    assert "Workspace format: 1" in backed_up.output
    assert "Files:" in backed_up.output
    assert "Bytes:" in backed_up.output
    assert f"Restored workspace: {target.resolve()}" in restored.output
    assert "SHA-256:" in restored.output
    assert "Workspace format: 1" in restored.output
    assert (target / "bundlewalker.toml").is_file()


def test_workspace_upgrade_current_is_noop(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    result = runner.invoke(app, ["workspace", "upgrade", str(workspace.root)])

    assert result.exit_code == 0, result.output
    assert result.output == "Workspace format 1 is already current.\n"
    assert list(tmp_path.glob("*.zip")) == []
    assert not (workspace.root / ".bundlewalker").exists()


def test_workspace_backup_pending_review_prints_all_remediation_commands(
    tmp_path: Path,
) -> None:
    root, review_id = _workspace_with_pending_review(tmp_path)
    output = tmp_path / "blocked.zip"

    result = runner.invoke(
        app,
        ["workspace", "backup", str(output), "--workspace", str(root)],
    )

    assert result.exit_code == 1
    assert f"Error: workspace already has a pending review: {review_id}" in result.output
    assert f"Pending review: {review_id}" in result.output
    assert "bundlewalker review show" in result.output
    assert f"bundlewalker review apply {review_id}" in result.output
    assert f"bundlewalker review discard {review_id}" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


@pytest.mark.parametrize(
    ("arguments", "expected_message", "expected_exit"),
    [
        (
            ["workspace", "restore", "invalid.zip", "restored"],
            "Error: backup archive verification failed",
            1,
        ),
        (
            ["workspace", "restore", "unused.zip", "occupied"],
            "Error: restore target must be a new or empty directory",
            2,
        ),
        (
            ["workspace", "backup", "future.zip", "--workspace", "future"],
            "Error: workspace format is not supported for this operation",
            2,
        ),
        (
            ["workspace", "upgrade", "unsupported"],
            "Error: no complete workspace migration path is available",
            2,
        ),
    ],
)
def test_workspace_errors_use_stable_messages_without_tracebacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected_message: str,
    expected_exit: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "invalid.zip").write_bytes(b"not a workspace backup")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    future = tmp_path / "future"
    future.mkdir()
    (future / "bundlewalker.toml").write_text("version = 2\n", encoding="utf-8")
    unsupported = tmp_path / "unsupported"
    unsupported.mkdir()
    (unsupported / "bundlewalker.toml").write_text("version = 0\n", encoding="utf-8")

    result = runner.invoke(app, arguments)

    assert result.exit_code == expected_exit
    assert expected_message in result.output
    assert "Traceback" not in result.output
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "future.zip").exists()


def test_workspace_upgrade_failure_prints_verified_backup_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    def fail_after_mutation(quiescent: QuiescentWorkspace) -> None:
        (quiescent.workspace.root / "bundlewalker.toml").write_text(
            "version = 2\n", encoding="utf-8"
        )
        raise RuntimeError("token=private-cause")

    application = LifecycleApplication(
        LifecycleDependencies(
            clock=lambda: NOW,
            target_version=2,
            migrations={
                1: MigrationStep(
                    1,
                    2,
                    fail_after_mutation,
                    lambda _workspace: None,
                )
            },
        )
    )
    monkeypatch.setattr(cli_module, "LifecycleApplication", lambda: application)

    result = runner.invoke(
        app,
        ["workspace", "upgrade", str(workspace.root), "--backup-dir", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert (
        "Error: workspace migration failed; restore the verified pre-upgrade backup"
        in result.output
    )
    assert "Verified pre-upgrade backup:" in result.output
    assert "SHA-256:" in result.output
    assert "private-cause" not in result.output
    assert "Traceback" not in result.output
    assert result.output.index("Error:") < result.output.index("Verified pre-upgrade backup:")
    archives = list(tmp_path.glob("*.zip"))
    assert len(archives) == 1
    assert str(archives[0]) in result.output


def _workspace_with_pending_review(tmp_path: Path) -> tuple[Path, str]:
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
    return workspace.root, prepared.transaction_id
