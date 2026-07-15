from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.errors import AgentRunError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import discard_transaction
from bundlewalker.workflows.ask import AnsweredQuestion, answer_question, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _workspace(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    concept = workspace.wiki_dir / "topics" / "agents.md"
    concept.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return workspace


def _answer(title: str = "Résumé of Agent Design") -> CitedAnswer:
    return CitedAnswer(
        title=title,
        body="# Answer\n\nAgents can use tools [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


async def test_plain_answer_is_read_only_including_transaction_recovery(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    unfinished = workspace.root / ".bundlewalker" / "transactions" / "unfinished"
    unfinished.mkdir(parents=True)
    (unfinished / "sentinel").write_bytes(b"must remain")
    before = _tree_bytes(workspace.root)
    calls = 0

    async def runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        assert model == "test:model"
        assert question == "How do agents use tools?"
        assert dependencies.repository.root == workspace.wiki_dir
        dependencies.read_ids.add("topics/agents")
        return _answer(), frozenset({"topics/agents"})

    result = await answer_question(
        workspace,
        "How do agents use tools?",
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert result == AnsweredQuestion(
        answer=_answer(),
        read_ids=frozenset({"topics/agents"}),
    )
    assert calls == 1
    assert _tree_bytes(workspace.root) == before


async def test_answer_workflow_revalidates_injected_runner_output(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    async def invalid_runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        return _answer(), frozenset()

    with pytest.raises(AgentRunError, match="not read"):
        await answer_question(
            workspace,
            "Question?",
            explicit_model="test:model",
            environment={},
            runner=invalid_runner,
        )


def test_prepare_synthesis_builds_one_validated_create_without_model_call(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    answered = AnsweredQuestion(
        answer=_answer(),
        read_ids=frozenset({"topics/agents"}),
    )

    transaction = prepare_synthesis(workspace, answered, occurred_at=NOW)

    change_set = transaction.change_set
    assert change_set.summary == "Saved synthesis: Résumé of Agent Design"
    assert change_set.source_sha256 is None
    assert len(change_set.drafts) == 1
    draft = change_set.drafts[0]
    assert draft.operation == "create"
    assert draft.path == "syntheses/resume-of-agent-design"
    assert draft.type == "Synthesis"
    assert draft.title == answered.answer.title
    assert draft.description == "A saved answer to a knowledge query."
    assert draft.tags == ["synthesis"]
    assert draft.body == answered.answer.body
    assert draft.citations == answered.answer.citations
    rendered = (transaction.prospective_wiki / "syntheses" / "resume-of-agent-design.md").read_text(
        encoding="utf-8"
    )
    assert "Agents can use tools [1]." in rendered
    assert "[1] [Agents](/topics/agents.md)" in rendered
    discard_transaction(transaction)


def test_synthesis_slug_avoids_case_folded_filesystem_collisions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    occupied = workspace.wiki_dir / "syntheses" / "RESUME-OF-AGENT-DESIGN.md"
    occupied.write_text(
        render_document(
            OkfMetadata(
                type="Synthesis",
                title="Existing",
                description="An existing synthesis.",
                timestamp=NOW,
            ),
            "# Existing\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    answered = AnsweredQuestion(
        answer=_answer(),
        read_ids=frozenset({"topics/agents"}),
    )

    transaction = prepare_synthesis(workspace, answered, occurred_at=NOW)

    assert transaction.change_set.drafts[0].path == "syntheses/resume-of-agent-design-2"
    discard_transaction(transaction)


def test_invalid_synthesis_answer_does_not_leave_a_staged_transaction(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    before = _tree_bytes(workspace.root)
    answered = AnsweredQuestion(answer=_answer(), read_ids=frozenset())

    with pytest.raises(AgentRunError, match="not read"):
        prepare_synthesis(workspace, answered, occurred_at=NOW)

    assert _tree_bytes(workspace.root) == before
