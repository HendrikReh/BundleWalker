from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import bundlewalker.workflows.ask as ask_workflow
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.cli import app
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workspace import initialize_workspace

runner = CliRunner()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_ask_help_does_not_require_a_workspace() -> None:
    result = runner.invoke(app, ["ask", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "QUESTION" in result.output
    assert "--model" in result.output
    assert "--save" in result.output


@pytest.fixture
def cli_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = initialize_workspace(tmp_path / "knowledge")
    concept = workspace.wiki_dir / "topics" / "agents.md"
    concept.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    monkeypatch.chdir(workspace.root)
    return workspace.root


def _answer() -> CitedAnswer:
    return CitedAnswer(
        title="Agent Tool Use",
        body="# Answer\n\nAgents can use tools [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


def _install_runner(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    async def fake_runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        calls.append(question)
        assert model == "test:model"
        dependencies.read_ids.add("topics/agents")
        return _answer(), frozenset({"topics/agents"})

    monkeypatch.setattr(ask_workflow, "run_query_agent", fake_runner)


def test_plain_ask_prints_answer_and_citations_without_writing(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install_runner(monkeypatch, calls)
    before = _tree_bytes(cli_workspace)

    result = runner.invoke(
        app,
        ["ask", "How do agents use tools?", "--model", "test:model"],
    )

    assert result.exit_code == 0, result.output
    assert "Agents can use tools [1]." in result.output
    assert "# Citations" in result.output
    assert "[1] [Agents](/topics/agents.md)" in result.output
    assert "Apply these changes?" not in result.output
    assert calls == ["How do agents use tools?"]
    assert _tree_bytes(cli_workspace) == before


@pytest.mark.parametrize("confirmation", ["n\n", ""])
def test_ask_save_decline_discards_review_without_second_model_call(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    confirmation: str,
) -> None:
    calls: list[str] = []
    _install_runner(monkeypatch, calls)
    before_wiki = _tree_bytes(cli_workspace / "wiki")

    result = runner.invoke(
        app,
        ["ask", "How do agents use tools?", "--model", "test:model", "--save"],
        input=confirmation,
    )

    assert result.exit_code == 0, result.output
    assert "Agents can use tools [1]." in result.output
    assert "Saved synthesis: Agent Tool Use" in result.output
    assert "--- wiki/" in result.output and "+++ wiki/" in result.output
    assert "No changes applied." in result.output
    assert calls == ["How do agents use tools?"]
    assert _tree_bytes(cli_workspace / "wiki") == before_wiki
    assert not list((cli_workspace / ".bundlewalker" / "transactions").glob("*"))


def test_ask_save_accepts_review_without_second_model_call(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install_runner(monkeypatch, calls)

    result = runner.invoke(
        app,
        ["ask", "How do agents use tools?", "--model", "test:model", "--save"],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == ["How do agents use tools?"]
    synthesis = cli_workspace / "wiki" / "syntheses" / "agent-tool-use.md"
    assert synthesis.is_file()
    text = synthesis.read_text(encoding="utf-8")
    assert "Agents can use tools [1]." in text
    assert "[1] [Agents](/topics/agents.md)" in text
    assert "Saved synthesis: Agent Tool Use" in (cli_workspace / "wiki" / "log.md").read_text(
        encoding="utf-8"
    )
