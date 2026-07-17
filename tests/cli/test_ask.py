from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import bundlewalker.workflows.ask as ask_workflow
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.cli import app
from bundlewalker.domain import Citation, CitedAnswer, OkfDocument, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import initialize_workspace

runner = CliRunner()
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


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
    assert "--refresh" in result.output
    assert "SYNTHESIS_ID" in result.output


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


def _write_refresh_target(
    root: Path,
    *,
    concept_id: str = "syntheses/current-agent-framework",
    concept_type: str = "Synthesis",
) -> OkfDocument:
    target = root / "wiki" / f"{concept_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_document(
            OkfMetadata.model_validate(
                {
                    "type": concept_type,
                    "title": "Current Agent Framework",
                    "description": "A maintained decision framework.",
                    "tags": ["agents", "decision-framework"],
                    "timestamp": NOW,
                    "owner": "hendrik",
                }
            ),
            "# Current answer\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(root / "wiki")
    return OkfRepository(root / "wiki").get(concept_id)


def _refreshed_answer() -> CitedAnswer:
    return CitedAnswer(
        title="Updated Agent Framework",
        body="# Updated answer\n\nCurrent evidence supports tool use [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


def _install_refresh_runner(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    *,
    answer: CitedAnswer | None = None,
) -> None:
    async def fake_runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
        target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        calls.append(question)
        assert model == "test:model"
        assert target.concept_id == "syntheses/current-agent-framework"
        dependencies.read_ids.add("topics/agents")
        return answer or _refreshed_answer(), frozenset({"topics/agents"})

    monkeypatch.setattr(ask_workflow, "run_refresh_query_agent", fake_runner)


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


def test_ask_cli_sanitizes_injected_raw_line_spans(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe = CitedAnswer.model_construct(
        title="Unsafe spans",
        body="Agents can use tools [1].",
        citations=[Citation(number=1, concept_id="topics/agents", start_line=1, end_line=2)],
    )

    async def fake_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/agents")
        return unsafe, frozenset({"topics/agents"})

    monkeypatch.setattr(ask_workflow, "run_query_agent", fake_runner)

    result = runner.invoke(app, ["ask", "Question?", "--model", "test:model"])

    assert result.exit_code == 1
    assert "line spans" in result.output
    assert "raw lines 1" not in result.output


def test_ask_save_and_refresh_are_mutually_exclusive_before_model_or_staging(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    model_resolutions: list[tuple[str | None, Mapping[str, str]]] = []

    def unexpected_model_resolution(
        explicit_model: str | None,
        environment: Mapping[str, str],
    ) -> str:
        model_resolutions.append((explicit_model, environment))
        raise AssertionError("model resolution must not run")

    _install_refresh_runner(monkeypatch, calls)
    monkeypatch.setattr(ask_workflow, "resolve_model", unexpected_model_resolution)
    before = _tree_bytes(cli_workspace)

    result = runner.invoke(
        app,
        [
            "ask",
            "Refresh this synthesis.",
            "--model",
            "test:model",
            "--save",
            "--refresh",
            "syntheses/current-agent-framework",
        ],
    )

    assert result.exit_code == 2
    assert "mutually exclusive" in result.output
    assert calls == []
    assert model_resolutions == []
    assert _tree_bytes(cli_workspace) == before
    assert not (cli_workspace / ".bundlewalker").exists()


@pytest.mark.parametrize(
    ("target_id", "write_target", "expected"),
    [
        ("Synthesis/Not-Canonical", False, "canonical Synthesis concept ID"),
        ("syntheses/missing", False, "does not exist"),
        ("syntheses/not-a-synthesis", True, "is not a Synthesis"),
    ],
)
def test_ask_refresh_rejects_invalid_target_before_model_or_staging(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_id: str,
    write_target: bool,
    expected: str,
) -> None:
    if write_target:
        _write_refresh_target(
            cli_workspace,
            concept_id=target_id,
            concept_type="Topic",
        )
    calls: list[str] = []
    model_resolutions: list[tuple[str | None, Mapping[str, str]]] = []

    def unexpected_model_resolution(
        explicit_model: str | None,
        environment: Mapping[str, str],
    ) -> str:
        model_resolutions.append((explicit_model, environment))
        raise AssertionError("model resolution must not run")

    _install_refresh_runner(monkeypatch, calls)
    monkeypatch.setattr(ask_workflow, "resolve_model", unexpected_model_resolution)
    before = _tree_bytes(cli_workspace)

    result = runner.invoke(
        app,
        [
            "ask",
            "Refresh this synthesis.",
            "--model",
            "test:model",
            "--refresh",
            target_id,
        ],
    )

    assert result.exit_code == 2
    assert expected in result.output
    assert calls == []
    assert model_resolutions == []
    assert _tree_bytes(cli_workspace) == before
    assert not (cli_workspace / ".bundlewalker").exists()


@pytest.mark.parametrize("confirmation", ["n\n", ""])
def test_ask_refresh_decline_or_interruption_discards_replacement(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    confirmation: str,
) -> None:
    target = _write_refresh_target(cli_workspace)
    calls: list[str] = []
    _install_refresh_runner(monkeypatch, calls)
    before_wiki = _tree_bytes(cli_workspace / "wiki")

    result = runner.invoke(
        app,
        [
            "ask",
            "Refresh this synthesis.",
            "--model",
            "test:model",
            "--refresh",
            target.concept_id,
        ],
        input=confirmation,
    )

    assert result.exit_code == 0, result.output
    assert "Current evidence supports tool use [1]." in result.output
    assert "Refreshed synthesis: Updated Agent Framework" in result.output
    assert "--- wiki/syntheses/current-agent-framework.md" in result.output
    assert "+++ wiki/syntheses/current-agent-framework.md" in result.output
    assert "No changes applied." in result.output
    assert calls == ["Refresh this synthesis."]
    assert _tree_bytes(cli_workspace / "wiki") == before_wiki
    assert not list((cli_workspace / ".bundlewalker" / "transactions").glob("*"))


def test_ask_refresh_accepts_in_place_and_preserves_metadata_extensions(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write_refresh_target(cli_workspace)
    calls: list[str] = []
    _install_refresh_runner(monkeypatch, calls)

    result = runner.invoke(
        app,
        [
            "ask",
            "Refresh this synthesis.",
            "--model",
            "test:model",
            "--refresh",
            target.concept_id,
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == ["Refresh this synthesis."]
    assert "Changes applied." in result.output
    refreshed = OkfRepository(cli_workspace / "wiki").get(target.concept_id)
    assert refreshed.path == target.path
    assert refreshed.metadata.title == "Updated Agent Framework"
    assert refreshed.metadata.description == "A maintained decision framework."
    assert refreshed.metadata.tags == ["agents", "decision-framework"]
    assert refreshed.metadata.model_extra == {"owner": "hendrik"}
    assert "Current evidence supports tool use [1]." in refreshed.body
    assert "[1] [Agents](/topics/agents.md)" in refreshed.body
    assert "Refreshed synthesis: Updated Agent Framework" in (
        cli_workspace / "wiki" / "log.md"
    ).read_text(encoding="utf-8")


def test_ask_equivalent_refresh_reports_no_op_without_prompt_or_staging(
    cli_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write_refresh_target(cli_workspace)
    answer = CitedAnswer(
        title="Current Agent Framework",
        body="# Current answer\n\nAgents can use tools [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )
    calls: list[str] = []
    _install_refresh_runner(monkeypatch, calls, answer=answer)
    render_calls: list[CitedAnswer] = []
    original_render = ask_workflow.render_cited_answer

    def tracking_render(answered: CitedAnswer, repository: OkfRepository) -> str:
        render_calls.append(answered)
        return original_render(answered, repository)

    monkeypatch.setattr(ask_workflow, "render_cited_answer", tracking_render)
    before = _tree_bytes(cli_workspace)

    result = runner.invoke(
        app,
        [
            "ask",
            "Refresh this synthesis.",
            "--model",
            "test:model",
            "--refresh",
            target.concept_id,
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Synthesis is already current; no changes applied." in result.output
    assert "Apply these changes?" not in result.output
    assert calls == ["Refresh this synthesis."]
    assert render_calls == [answer]
    assert _tree_bytes(cli_workspace) == before
    assert not (cli_workspace / ".bundlewalker").exists()
