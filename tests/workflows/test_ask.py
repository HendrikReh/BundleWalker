from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.workflows.ask as ask_workflow
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import (
    MAX_ANSWER_BODY_CHARACTERS,
    Citation,
    CitedAnswer,
    DraftConcept,
    OkfDocument,
    OkfMetadata,
)
from bundlewalker.errors import AgentRunError, ChangeSetError, ReviewPendingError, UsageError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import PreparedTransaction, discard_transaction, get_pending_review
from bundlewalker.workflows.ask import (
    AnsweredQuestion,
    AnsweredSynthesisRefresh,
    SynthesisAlreadyCurrent,
    answer_question,
    answer_synthesis_refresh,
    prepare_synthesis,
    prepare_synthesis_refresh,
)
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
REFRESHED_AT = datetime(2026, 7, 16, 14, 30, tzinfo=UTC)


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


def _write_refresh_target(
    workspace: Workspace,
    *,
    concept_id: str = "syntheses/current-agent-framework",
    concept_type: str = "Synthesis",
    title: str = "Current Agent Framework",
    description: str | None = "A maintained decision framework.",
    timestamp: datetime | None = NOW,
    tags: list[str] | None = None,
) -> OkfDocument:
    target = workspace.wiki_dir / f"{concept_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata_values: dict[str, object] = {
        "type": concept_type,
        "title": title,
        "tags": tags if tags is not None else ["agents", "decision-framework"],
        "owner": "hendrik",
    }
    if description is not None:
        metadata_values["description"] = description
    if timestamp is not None:
        metadata_values["timestamp"] = timestamp
    metadata = OkfMetadata.model_validate(metadata_values)
    target.write_text(
        render_document(
            metadata,
            "# Current answer\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return OkfRepository(workspace.wiki_dir).get(concept_id)


def _refreshed_answer() -> CitedAnswer:
    return CitedAnswer(
        title="Updated Agent Framework",
        body="# Updated answer\n\nCurrent evidence supports tool use [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


def _set_swapping_after_old(prepared: PreparedTransaction) -> None:
    manifest_path = prepared.transaction_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = "swapping"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)


async def test_plain_answer_without_pending_transaction_is_read_only(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
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


async def test_answer_recovers_authenticated_swap_before_query_runner(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepared = prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=_answer("Interrupted synthesis"),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    expected_wiki = _tree_bytes(workspace.wiki_dir)
    _set_swapping_after_old(prepared)
    assert not workspace.wiki_dir.exists()
    assert prepared.backup_wiki.is_dir()

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        assert workspace.wiki_dir.is_dir()
        assert not prepared.transaction_dir.exists()
        dependencies.read_ids.add("topics/agents")
        return _answer(), frozenset({"topics/agents"})

    result = await answer_question(
        workspace,
        "How do agents use tools?",
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert result.answer == _answer()
    assert result.read_ids == frozenset({"topics/agents"})
    assert _tree_bytes(workspace.wiki_dir) == expected_wiki
    assert not prepared.transaction_dir.exists()


async def test_refresh_recovers_authenticated_swap_before_target_validation_and_runner(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    prepared = prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=_answer("Interrupted synthesis"),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    expected_wiki = _tree_bytes(workspace.wiki_dir)
    _set_swapping_after_old(prepared)
    assert not workspace.wiki_dir.exists()
    assert prepared.backup_wiki.is_dir()

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        received_target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        assert workspace.wiki_dir.is_dir()
        assert not prepared.transaction_dir.exists()
        assert received_target == target
        assert dependencies.repository.get(target.concept_id) == target
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset({"topics/agents"})

    result = await answer_synthesis_refresh(
        workspace,
        "Refresh after recovery.",
        target.concept_id,
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert result.target == target
    assert result.answer == _refreshed_answer()
    assert _tree_bytes(workspace.wiki_dir) == expected_wiki
    assert not prepared.transaction_dir.exists()


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


async def test_answer_workflow_rejects_injected_raw_line_spans(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    unsafe = CitedAnswer.model_construct(
        title="Unsafe spans",
        body="Agents use tools [1].",
        citations=[Citation(number=1, concept_id="topics/agents", start_line=1, end_line=2)],
    )

    async def invalid_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/agents")
        return unsafe, frozenset({"topics/agents"})

    with pytest.raises(AgentRunError, match="line spans") as caught:
        await answer_question(
            workspace,
            "Question?",
            explicit_model="test:model",
            environment={},
            runner=invalid_runner,
        )

    assert caught.value.__cause__ is None


async def test_answer_workflow_rejects_injected_oversized_answer(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    oversized = CitedAnswer.model_construct(
        title="Oversized",
        body="x" * (MAX_ANSWER_BODY_CHARACTERS + 1),
        citations=[Citation(number=1, concept_id="topics/agents")],
    )

    async def invalid_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/agents")
        return oversized, frozenset({"topics/agents"})

    with pytest.raises(AgentRunError, match="output size"):
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


def test_prepare_synthesis_rechecks_a_pending_review_before_transaction_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(answer=_answer("First synthesis"), read_ids=frozenset({"topics/agents"})),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None

    def must_not_prepare_transaction(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pending synthesis reached transaction preparation")

    monkeypatch.setattr(ask_workflow, "prepare_transaction", must_not_prepare_transaction)

    with pytest.raises(ReviewPendingError):
        prepare_synthesis(
            workspace,
            AnsweredQuestion(
                answer=_answer("Second synthesis"),
                read_ids=frozenset({"topics/agents"}),
            ),
            occurred_at=NOW,
        )

    current = get_pending_review(workspace)
    assert current is not None
    assert current.review_id == pending.review_id


async def test_refresh_rejects_a_pending_review_before_invoking_the_model(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(answer=_answer("First synthesis"), read_ids=frozenset({"topics/agents"})),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("pending refresh invoked the model runner")

    with pytest.raises(ReviewPendingError):
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model="test:model",
            environment={},
            runner=must_not_run,
        )

    assert calls == 0
    current = get_pending_review(workspace)
    assert current is not None
    assert current.review_id == pending.review_id


async def test_answer_question_leaves_a_pending_review_untouched(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=_answer("Pending synthesis"),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/agents")
        return _answer(), frozenset({"topics/agents"})

    result = await answer_question(
        workspace,
        "How do agents use tools?",
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert result.answer == _answer()
    current = get_pending_review(workspace)
    assert current is not None
    assert current.review_id == pending.review_id


@pytest.mark.parametrize(
    "concept_id",
    [
        "syntheses/Current-Agent-Framework",
        "syntheses/current-agent-framework.md",
        "syntheses/current_agent_framework",
        "syntheses/../topics/agents",
        "topics/agents",
    ],
)
async def test_refresh_rejects_noncanonical_target_before_model_resolution(
    tmp_path: Path,
    concept_id: str,
) -> None:
    workspace = _workspace(tmp_path)
    before = _tree_bytes(workspace.root)
    calls = 0

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return _refreshed_answer(), frozenset({"topics/agents"})

    with pytest.raises(UsageError, match="canonical Synthesis concept ID"):
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            concept_id,
            explicit_model=None,
            environment={},
            runner=runner,
        )

    assert calls == 0
    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


async def test_refresh_rejects_missing_target_before_model_resolution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    before = _tree_bytes(workspace.root)
    calls = 0

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return _refreshed_answer(), frozenset({"topics/agents"})

    with pytest.raises(UsageError, match="does not exist"):
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            "syntheses/missing",
            explicit_model=None,
            environment={},
            runner=runner,
        )

    assert calls == 0
    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


async def test_refresh_rejects_non_synthesis_target_before_model_resolution(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target_id = "syntheses/not-a-synthesis"
    _write_refresh_target(workspace, concept_id=target_id, concept_type="Topic")
    before = _tree_bytes(workspace.root)
    calls = 0

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return _refreshed_answer(), frozenset({"topics/agents"})

    with pytest.raises(UsageError, match="not a Synthesis"):
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target_id,
            explicit_model=None,
            environment={},
            runner=runner,
        )

    assert calls == 0
    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


@pytest.mark.parametrize(
    ("concept_id", "description", "tags"),
    [
        ("syntheses/oversized-description", "x" * 1_001, None),
        ("syntheses/empty-tag", "A maintained decision framework.", [""]),
        ("syntheses/oversized-tag", "A maintained decision framework.", ["x" * 81]),
        (
            "syntheses/too-many-tags",
            "A maintained decision framework.",
            [f"tag-{index}" for index in range(33)],
        ),
        (
            f"syntheses/{'a' * 231}",
            "A maintained decision framework.",
            None,
        ),
    ],
)
async def test_refresh_rejects_preserved_metadata_outside_producer_limits_before_model(
    tmp_path: Path,
    concept_id: str,
    description: str,
    tags: list[str] | None,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(
        workspace,
        concept_id=concept_id,
        description=description,
        tags=tags,
    )
    before = _tree_bytes(workspace.root)
    calls = 0

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return _refreshed_answer(), frozenset({"topics/agents"})

    with pytest.raises(UsageError, match="metadata exceeds supported producer limits") as caught:
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model=None,
            environment={},
            runner=runner,
        )

    assert caught.value.__cause__ is None
    assert calls == 0
    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


async def test_refresh_prevalidation_allows_oversized_historical_title(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace, title="x" * 301)

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        received_target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        assert received_target == target
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset({"topics/agents"})

    result = await answer_synthesis_refresh(
        workspace,
        "Replace the historical title.",
        target.concept_id,
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert result.answer.title == "Updated Agent Framework"


async def test_answer_refresh_passes_exact_target_and_verifies_actual_reads(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    expected_target = _write_refresh_target(workspace)
    received_targets: list[OkfDocument] = []

    async def runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
        target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        assert model == "test:model"
        assert question == "Refresh using current evidence."
        received_targets.append(target)
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset({"topics/agents"})

    result = await answer_synthesis_refresh(
        workspace,
        "Refresh using current evidence.",
        expected_target.concept_id,
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert received_targets == [expected_target]
    assert result == AnsweredSynthesisRefresh(
        answer=_refreshed_answer(),
        read_ids=frozenset({"topics/agents"}),
        target=received_targets[0],
    )


async def test_answer_refresh_uses_default_refresh_query_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    calls = 0

    async def default_runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
        received_target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        assert model == "test:model"
        assert dependencies.repository.root == workspace.wiki_dir
        assert question == "Use the default refresh route."
        assert received_target == target
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset({"topics/agents"})

    monkeypatch.setattr(ask_workflow, "run_refresh_query_agent", default_runner)

    result = await answer_synthesis_refresh(
        workspace,
        "Use the default refresh route.",
        target.concept_id,
        explicit_model="test:model",
        environment={},
        runner=None,
    )

    assert calls == 1
    assert result == AnsweredSynthesisRefresh(
        answer=_refreshed_answer(),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )


async def test_answer_refresh_rejects_runner_read_history_mismatch(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset()

    with pytest.raises(AgentRunError, match="read history"):
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model="test:model",
            environment={},
            runner=runner,
        )


async def test_answer_refresh_independently_rejects_nonexistent_citation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    invalid = CitedAnswer(
        title="Unsupported refresh",
        body="This claim has no live support [1].",
        citations=[Citation(number=1, concept_id="topics/missing")],
    )

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add("topics/missing")
        return invalid, frozenset({"topics/missing"})

    with pytest.raises(AgentRunError, match="citation target does not exist") as caught:
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model="test:model",
            environment={},
            runner=runner,
        )

    assert caught.value.__cause__ is None


async def test_answer_refresh_sanitizes_malformed_injected_citation_shape(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    malformed = CitedAnswer.model_construct(
        title="Malformed refresh",
        body="Malformed citation [1].",
        citations=[object()],
    )

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        return malformed, frozenset()

    with pytest.raises(AgentRunError, match="query citations could not be checked") as caught:
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model="test:model",
            environment={},
            runner=runner,
        )

    assert caught.value.__cause__ is None


async def test_answer_refresh_rejects_self_citation_from_injected_runner(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    self_citing = CitedAnswer(
        title="Circular update",
        body="The previous synthesis already answers this [1].",
        citations=[Citation(number=1, concept_id=target.concept_id)],
    )

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        dependencies.read_ids.add(target.concept_id)
        return self_citing, frozenset({target.concept_id})

    with pytest.raises(AgentRunError, match="cannot cite itself") as caught:
        await answer_synthesis_refresh(
            workspace,
            "Refresh this synthesis.",
            target.concept_id,
            explicit_model="test:model",
            environment={},
            runner=runner,
        )

    assert caught.value.__cause__ is None


async def test_prepare_refresh_builds_one_digest_protected_replace_without_second_model_call(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    calls = 0

    async def runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _question: str,
        received_target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        assert received_target == target
        dependencies.read_ids.add("topics/agents")
        return _refreshed_answer(), frozenset({"topics/agents"})

    answered = await answer_synthesis_refresh(
        workspace,
        "Refresh this synthesis.",
        target.concept_id,
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    transaction = prepare_synthesis_refresh(workspace, answered, occurred_at=REFRESHED_AT)

    assert calls == 1
    assert isinstance(transaction, PreparedTransaction)
    assert transaction.change_set.summary == "Refreshed synthesis: Updated Agent Framework"
    assert transaction.change_set.source_sha256 is None
    assert len(transaction.change_set.drafts) == 1
    draft = transaction.change_set.drafts[0]
    assert draft.operation == "replace"
    assert draft.path == target.concept_id
    assert draft.type == "Synthesis"
    assert draft.title == "Updated Agent Framework"
    assert draft.description == "A maintained decision framework."
    assert draft.tags == ["agents", "decision-framework"]
    assert draft.body == _refreshed_answer().body
    assert draft.citations == _refreshed_answer().citations
    assert draft.base_digest == target.digest
    rendered = (
        transaction.prospective_wiki / "syntheses" / "current-agent-framework.md"
    ).read_text(encoding="utf-8")
    assert "title: Updated Agent Framework" in rendered
    assert "owner: hendrik" in rendered
    assert "Current evidence supports tool use [1]." in rendered
    assert "[1] [Agents](/topics/agents.md)" in rendered
    refreshed = OkfRepository(transaction.prospective_wiki).get(target.concept_id)
    assert refreshed.metadata.timestamp == REFRESHED_AT
    assert refreshed.metadata.model_extra == {"owner": "hendrik"}
    log = (transaction.prospective_wiki / "log.md").read_text(encoding="utf-8")
    assert "## 2026-07-16" in log
    assert "Refreshed synthesis: Updated Agent Framework" in log
    discard_transaction(transaction)


def test_prepare_refresh_uses_default_description_when_target_omits_it(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace, description=None)
    assert target.metadata.description is None
    answered = AnsweredSynthesisRefresh(
        answer=_refreshed_answer(),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )

    transaction = prepare_synthesis_refresh(workspace, answered, occurred_at=REFRESHED_AT)

    assert isinstance(transaction, PreparedTransaction)
    draft = transaction.change_set.drafts[0]
    assert draft.description == "A saved answer to a knowledge query."
    refreshed = OkfRepository(transaction.prospective_wiki).get(target.concept_id)
    assert refreshed.metadata.description == "A saved answer to a knowledge query."
    assert refreshed.metadata.model_extra == {"owner": "hendrik"}
    discard_transaction(transaction)


def test_prepare_refresh_uses_occurred_at_when_target_omits_timestamp(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace, timestamp=None)
    assert target.metadata.timestamp is None
    answered = AnsweredSynthesisRefresh(
        answer=_refreshed_answer(),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )

    transaction = prepare_synthesis_refresh(workspace, answered, occurred_at=REFRESHED_AT)

    assert isinstance(transaction, PreparedTransaction)
    refreshed = OkfRepository(transaction.prospective_wiki).get(target.concept_id)
    assert refreshed.metadata.timestamp == REFRESHED_AT
    assert refreshed.metadata.model_extra == {"owner": "hendrik"}
    discard_transaction(transaction)


def test_prepare_refresh_rejects_target_changed_since_answer_without_staging(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    answered = AnsweredSynthesisRefresh(
        answer=_refreshed_answer(),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )
    target.path.write_text(
        render_document(
            target.metadata,
            "# Concurrent edit\n\nAgents can use tools differently [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    before = _tree_bytes(workspace.root)

    with pytest.raises(ChangeSetError, match="stale base digest"):
        prepare_synthesis_refresh(workspace, answered, occurred_at=NOW)

    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


def test_prepare_equivalent_refresh_is_canonical_no_op(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    answered = AnsweredSynthesisRefresh(
        answer=CitedAnswer(
            title="Current Agent Framework",
            body="# Current answer\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )
    before = _tree_bytes(workspace.root)

    result = prepare_synthesis_refresh(workspace, answered, occurred_at=NOW)

    assert result == SynthesisAlreadyCurrent(target.concept_id)
    assert _tree_bytes(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


def test_prepare_no_op_rechecks_live_target_after_canonical_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    target = _write_refresh_target(workspace)
    answered = AnsweredSynthesisRefresh(
        answer=CitedAnswer(
            title="Current Agent Framework",
            body="# Current answer\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        read_ids=frozenset({"topics/agents"}),
        target=target,
    )
    original_render = ask_workflow.render_draft

    def racing_render(
        draft: DraftConcept,
        context: ChangeValidationContext,
        *,
        occurred_at: datetime,
        prospective_drafts: Iterable[DraftConcept] = (),
    ) -> str:
        canonical = original_render(
            draft,
            context,
            occurred_at=occurred_at,
            prospective_drafts=prospective_drafts,
        )
        target.path.write_text(
            render_document(
                target.metadata,
                "# Concurrent edit\n\nAgents now use different tools [1].\n\n"
                "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
            ),
            encoding="utf-8",
        )
        return canonical

    monkeypatch.setattr(ask_workflow, "render_draft", racing_render)

    with pytest.raises(ChangeSetError, match="stale base digest"):
        prepare_synthesis_refresh(workspace, answered, occurred_at=NOW)

    assert not (workspace.root / ".bundlewalker").exists()
