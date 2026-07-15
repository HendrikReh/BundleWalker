from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from typer.testing import CliRunner

import bundlewalker.workflows.lint as lint_workflow
from bundlewalker.agents.common import AgentDependencies, read_concept
from bundlewalker.agents.semantic_lint import AgentModel
from bundlewalker.cli import app
from bundlewalker.domain import FindingOrigin, LintFinding, OkfMetadata, Severity
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
runner = CliRunner()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, regenerate: bool) -> Path:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.wiki_dir / "topics" / "agents.md").write_text(
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
    if regenerate:
        regenerate_indexes(workspace.wiki_dir)
    monkeypatch.chdir(workspace.root)
    return workspace.root


def test_lint_help_does_not_require_a_workspace() -> None:
    result = runner.invoke(app, ["lint", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--semantic" in result.output
    assert "--model" in result.output


def test_plain_lint_reports_sorted_findings_and_exits_on_deterministic_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, monkeypatch, regenerate=False)
    before = _tree_bytes(root)

    result = runner.invoke(app, ["lint"])

    assert result.exit_code == 1, result.output
    assert result.output.index("INDEX001") < result.output.index("ORPHAN001")
    assert "deterministic" in result.output
    assert _tree_bytes(root) == before


def test_semantic_lint_requires_a_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _workspace(tmp_path, monkeypatch, regenerate=True)
    monkeypatch.delenv("BUNDLEWALKER_MODEL", raising=False)

    result = runner.invoke(app, ["lint", "--semantic"])

    assert result.exit_code == 2
    assert "--model MODEL" in result.output
    assert "BUNDLEWALKER_MODEL" in result.output


def test_semantic_findings_are_printed_but_do_not_control_exit_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, monkeypatch, regenerate=True)
    before = _tree_bytes(root)

    async def fake_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        read_result = read_concept(
            RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
            "topics/agents",
        )
        assert "error" not in read_result
        return (
            [
                LintFinding(
                    origin=FindingOrigin.SEMANTIC,
                    severity=Severity.ERROR,
                    code="SEM-UNSUPPORTED",
                    path="topics/agents.md",
                    message="A claim needs stronger support.",
                    evidence_paths=["topics/agents"],
                )
            ],
            frozenset({"topics/agents"}),
        )

    monkeypatch.setattr(lint_workflow, "run_semantic_lint_agent", fake_runner)

    result = runner.invoke(app, ["lint", "--semantic", "--model", "test:model"])

    assert result.exit_code == 0, result.output
    assert "SEM-UNSUPPORTED" in result.output
    assert "semantic" in result.output
    assert "ORPHAN001" in result.output
    assert _tree_bytes(root) == before
