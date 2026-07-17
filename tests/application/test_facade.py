from __future__ import annotations

from base64 import urlsafe_b64decode
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.workflows.ask as ask_workflow
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.application import (
    MAX_QUESTION_CHARACTERS,
    ApplicationDependencies,
    ApplicationError,
    ApplicationErrorCode,
    InlineSource,
    WorkspaceApplication,
)
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    OkfDocument,
    OkfMetadata,
)
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import get_pending_review
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import RawSource, Workspace, initialize_workspace, load_inline_source

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.wiki_dir / "topics" / "agents.md").write_text(
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
    (workspace.wiki_dir / "entities" / "tools.md").write_text(
        render_document(
            OkfMetadata(type="Entity", tags=["tools"], timestamp=NOW),
            "# Tools\n\nTools support agent workflows.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return workspace


def _answer() -> CitedAnswer:
    return CitedAnswer(
        title="Agent tools",
        body="# Answer\n\nAgents can use tools [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )


def _ingestion_change_set(source: RawSource) -> ChangeSet:
    return ChangeSet(
        summary="Integrated notes.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Notes",
                description="Notes from the incoming source.",
                tags=["notes"],
                body="# Notes\n\nThe source contains text [1].\n",
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


async def _ingestion_runner(
    model: AgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    assert model == "test:model"
    return _ingestion_change_set(source), frozenset()


def _live_tree_bytes(workspace: Workspace) -> dict[str, bytes]:
    return {
        path.relative_to(workspace.root).as_posix(): path.read_bytes()
        for root in (workspace.wiki_dir, workspace.raw_dir)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _write_refresh_target(
    workspace: Workspace,
    *,
    concept_id: str = "syntheses/current-agent-framework",
    concept_type: str = "Synthesis",
) -> None:
    path = workspace.wiki_dir / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_document(
            OkfMetadata(
                type=concept_type,
                title="Current Agent Framework",
                description="A maintained decision framework.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Current answer\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)


async def _current_refresh_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    instruction: str,
    target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert instruction == "Refresh this answer"
    assert target.concept_id == "syntheses/current-agent-framework"
    dependencies.read_ids.add("topics/agents")
    return (
        CitedAnswer(
            title="Current Agent Framework",
            body="# Current answer\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        frozenset({"topics/agents"}),
    )


async def _query_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    question: str,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert question == "What do agents use?"
    dependencies.read_ids.add("topics/agents")
    return _answer(), frozenset({"topics/agents"})


@pytest.fixture
def application(tmp_path: Path) -> WorkspaceApplication:
    return WorkspaceApplication(
        _workspace(tmp_path),
        ApplicationDependencies(
            environment={},
            ingestion_runner=_ingestion_runner,
            query_runner=_query_runner,
        ),
    )


@pytest.fixture
def application_with_pending_review(tmp_path: Path) -> WorkspaceApplication:
    workspace = _workspace(tmp_path)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(answer=_answer(), read_ids=frozenset({"topics/agents"})),
        occurred_at=NOW,
    )
    return WorkspaceApplication(
        workspace,
        ApplicationDependencies(environment={}, query_runner=_query_runner),
    )


async def test_status_returns_counts_and_compact_pending_review(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    status = await application_with_pending_review.status()

    assert status.display_name == "knowledge"
    assert status.config_version == 1
    assert status.concept_counts == {"Entity": 1, "Topic": 1}
    assert status.pending_review is not None
    assert status.pending_review.summary.startswith("Saved synthesis")
    assert "diff" not in status.pending_review.model_dump()
    assert "changed_paths" not in status.pending_review.model_dump()


async def test_list_concepts_uses_opaque_cursor_without_duplicates(
    application: WorkspaceApplication,
) -> None:
    first = await application.list_concepts(limit=1)
    second = await application.list_concepts(cursor=first.next_cursor, limit=1)

    assert len(first.items) == 1
    assert len(second.items) == 1
    assert first.items[0].concept_id != second.items[0].concept_id
    assert first.next_cursor is not None
    assert "/" not in first.next_cursor


@pytest.mark.parametrize("cursor", ["not base64!", "dG9waWNzLy4u", "_w"])
async def test_list_concepts_rejects_tampered_cursor(
    application: WorkspaceApplication,
    cursor: str,
) -> None:
    with pytest.raises(ApplicationError) as raised:
        await application.list_concepts(cursor=cursor)

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "cursor",
    [
        "ZW50aXRpZXMvdG9vbHM=",
        "ZW50aXRpZXMvdG9vbHN",
    ],
)
async def test_list_concepts_rejects_noncanonical_cursor_encodings(
    application: WorkspaceApplication,
    cursor: str,
) -> None:
    assert urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)) == b"entities/tools"

    with pytest.raises(ApplicationError) as raised:
        await application.list_concepts(cursor=cursor)

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT


@pytest.mark.parametrize("limit", [0, 101])
async def test_list_concepts_rejects_limit_outside_page_bounds(
    application: WorkspaceApplication,
    limit: int,
) -> None:
    with pytest.raises(ApplicationError) as raised:
        await application.list_concepts(limit=limit)

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT


async def test_read_concept_returns_markdown_and_safe_metadata(
    application: WorkspaceApplication,
) -> None:
    result = await application.read_concept("entities/tools")

    assert result.title == "tools"
    assert result.description == ""
    assert result.resource_uri == "bundlewalker://concept/entities/tools"
    assert result.markdown.startswith("---\n")
    assert str(application.workspace.root) not in result.model_dump_json()


async def test_read_concept_translates_missing_concept(application: WorkspaceApplication) -> None:
    with pytest.raises(ApplicationError) as raised:
        await application.read_concept("topics/missing")

    assert raised.value.code is ApplicationErrorCode.CONCEPT_NOT_FOUND


@pytest.mark.parametrize("concept_id", ["", "../private", "topics\\agents", "topics//agents"])
async def test_read_concept_rejects_unsafe_concept_identifier(
    application: WorkspaceApplication,
    concept_id: str,
) -> None:
    with pytest.raises(ApplicationError) as raised:
        await application.read_concept(concept_id)

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT


async def test_search_concepts_returns_lexical_matches(application: WorkspaceApplication) -> None:
    result = await application.search_concepts("agents", concept_type="Topic", limit=1)

    assert [item.concept_id for item in result.items] == ["topics/agents"]
    assert result.items[0].resource_uri == "bundlewalker://concept/topics/agents"


async def test_ask_uses_injected_offline_runner(application: WorkspaceApplication) -> None:
    result = await application.ask("What do agents use?", explicit_model="test:model")

    assert result.answer == _answer()
    assert result.markdown.startswith("# Answer")


async def test_lint_runs_deterministically(application: WorkspaceApplication) -> None:
    result = await application.lint(semantic=False, explicit_model=None)

    assert result.deterministic_has_errors is False
    assert all(finding.origin.value == "deterministic" for finding in result.findings)


async def test_read_only_ask_works_while_review_is_pending(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    result = await application_with_pending_review.ask(
        "What do agents use?",
        explicit_model="test:model",
    )

    assert result.answer.body.startswith("# Answer")
    assert (await application_with_pending_review.get_pending_review()) is not None


async def test_pending_review_exposes_persisted_fields_and_no_path(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    review = await application_with_pending_review.get_pending_review()
    persisted = get_pending_review(application_with_pending_review.workspace)

    assert review is not None
    assert persisted is not None
    assert review.review_id == persisted.review_id
    assert review.diff == persisted.diff
    assert review.changed_paths == persisted.changed_paths
    assert review.resource_uri == "bundlewalker://review/pending"
    assert str(application_with_pending_review.workspace.root) not in review.model_dump_json()


async def test_inline_ingestion_returns_persisted_review_without_live_mutation(
    application: WorkspaceApplication,
) -> None:
    before = _live_tree_bytes(application.workspace)

    result = await application.prepare_ingestion(
        InlineSource(source_name="notes.txt", content="source text\n"),
        explicit_model="test:model",
    )
    persisted = get_pending_review(application.workspace)

    assert result.status == "pending"
    assert result.review is not None
    assert result.review.diff
    assert persisted is not None
    assert result.review.diff == persisted.diff
    assert result.review.changed_paths == persisted.changed_paths
    assert _live_tree_bytes(application.workspace) == before


async def test_file_ingestion_has_the_same_pending_review_contract(
    application: WorkspaceApplication,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "notes.txt"
    source_path.write_text("source text\n", encoding="utf-8")
    before = _live_tree_bytes(application.workspace)

    result = await application.prepare_file_ingestion(
        source_path,
        explicit_model="test:model",
    )

    assert result.status == "pending"
    assert result.review is not None
    assert result.review == await application.get_pending_review()
    assert _live_tree_bytes(application.workspace) == before


async def test_duplicate_inline_source_is_a_successful_typed_outcome(
    application: WorkspaceApplication,
) -> None:
    source = InlineSource(source_name="notes.txt", content="source text\n")
    first = await application.prepare_ingestion(source, explicit_model="test:model")
    assert first.review is not None
    await application.apply_review(first.review.review_id)

    duplicate = await application.prepare_ingestion(source, explicit_model=None)

    assert duplicate.status == "duplicate"
    assert duplicate.review is None


async def test_saved_synthesis_uses_one_model_call_and_persisted_review(
    tmp_path: Path,
) -> None:
    calls = 0

    async def runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        return await _query_runner(model, dependencies, question)

    application = WorkspaceApplication(
        _workspace(tmp_path),
        ApplicationDependencies(environment={}, query_runner=runner, clock=lambda: NOW),
    )

    result = await application.prepare_synthesis(
        "What do agents use?",
        explicit_model="test:model",
    )
    persisted = get_pending_review(application.workspace)

    assert calls == 1
    assert result.answer.answer == _answer()
    assert persisted is not None
    assert result.review.review_id == persisted.review_id
    assert result.review.diff == persisted.diff


async def test_refresh_reports_current_without_review(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _write_refresh_target(workspace)
    application = WorkspaceApplication(
        workspace,
        ApplicationDependencies(
            environment={},
            refresh_runner=_current_refresh_runner,
            clock=lambda: NOW,
        ),
    )

    result = await application.prepare_refresh(
        "Refresh this answer",
        "syntheses/current-agent-framework",
        explicit_model="test:model",
    )

    assert result.status == "current"
    assert result.concept_id == "syntheses/current-agent-framework"
    assert result.review is None
    assert await application.get_pending_review() is None


async def test_preparation_rejects_pending_review_before_model_call(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("pending synthesis invoked model runner")

    blocked = WorkspaceApplication(
        application_with_pending_review.workspace,
        ApplicationDependencies(environment={}, query_runner=must_not_run),
    )

    with pytest.raises(ApplicationError) as raised:
        await blocked.prepare_synthesis("Question", explicit_model="test:model")

    assert raised.value.code is ApplicationErrorCode.REVIEW_PENDING
    assert calls == 0


@pytest.mark.parametrize(
    ("instruction", "concept_id", "target_type", "expected_message"),
    [
        (" ", "syntheses/current-agent-framework", "Synthesis", "question must not be empty"),
        (
            "x" * (MAX_QUESTION_CHARACTERS + 1),
            "syntheses/current-agent-framework",
            "Synthesis",
            "refresh instruction exceeds the supported limit",
        ),
        (
            "Refresh this answer",
            "syntheses/missing",
            None,
            "refresh target does not exist",
        ),
        (
            "Refresh this answer",
            "syntheses/not-a-synthesis",
            "Topic",
            "refresh target is not a Synthesis",
        ),
    ],
    ids=["empty", "oversized", "missing-target", "wrong-target-type"],
)
async def test_refresh_validation_precedes_pending_review_through_facade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instruction: str,
    concept_id: str,
    target_type: str | None,
    expected_message: str,
) -> None:
    workspace = _workspace(tmp_path)
    if target_type is not None:
        _write_refresh_target(
            workspace,
            concept_id=concept_id,
            concept_type=target_type,
        )
    prepare_synthesis(
        workspace,
        AnsweredQuestion(answer=_answer(), read_ids=frozenset({"topics/agents"})),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None
    runner_calls = 0
    model_resolutions = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _instruction: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal runner_calls
        runner_calls += 1
        raise AssertionError("invalid refresh invoked provider")

    def must_not_resolve_model(*_args: object, **_kwargs: object) -> str:
        nonlocal model_resolutions
        model_resolutions += 1
        raise AssertionError("invalid refresh resolved a model")

    monkeypatch.setattr(ask_workflow, "resolve_model", must_not_resolve_model)
    application = WorkspaceApplication(
        workspace,
        ApplicationDependencies(environment={}, refresh_runner=must_not_run),
    )

    with pytest.raises(ApplicationError) as raised:
        await application.prepare_refresh(
            instruction,
            concept_id,
            explicit_model="test:model",
        )

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT
    assert raised.value.safe_message == expected_message
    assert runner_calls == 0
    assert model_resolutions == 0
    current = get_pending_review(workspace)
    assert current is not None
    assert current.review_id == pending.review_id


async def test_review_resolves_exactly_once(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None

    applied = await application_with_pending_review.apply_review(pending.review_id)

    assert applied.status == "applied"
    with pytest.raises(ApplicationError) as raised:
        await application_with_pending_review.apply_review(pending.review_id)
    assert raised.value.code is ApplicationErrorCode.REVIEW_NOT_FOUND


async def test_wrong_review_id_does_not_resolve_pending_review(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None

    with pytest.raises(ApplicationError) as raised:
        await application_with_pending_review.discard_review("0" * 32)

    assert raised.value.code is ApplicationErrorCode.REVIEW_ID_MISMATCH
    assert await application_with_pending_review.get_pending_review() == pending


async def test_stale_review_cannot_apply(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None
    (application_with_pending_review.workspace.wiki_dir / "external.md").write_text(
        "external edit\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError) as raised:
        await application_with_pending_review.apply_review(pending.review_id)

    assert raised.value.code is ApplicationErrorCode.REVIEW_STALE


async def test_raw_conflict_is_discoverable_and_discardable_after_facade_restart(
    application: WorkspaceApplication,
) -> None:
    source = load_inline_source("notes.txt", "external evidence\n", application.workspace)
    prepared = await application.prepare_ingestion(
        InlineSource(source_name="notes.txt", content="external evidence\n"),
        explicit_model="test:model",
    )
    assert prepared.review is not None
    destination = application.workspace.root / source.stored_relative_path
    destination.write_bytes(b"external conflicting bytes\n")
    restarted = WorkspaceApplication(application.workspace)

    loaded = await restarted.get_pending_review()
    status = await restarted.status()

    assert loaded is not None
    assert loaded.review_id == prepared.review.review_id
    assert loaded.diff == prepared.review.diff
    assert loaded.status.value == "stale"
    assert status.pending_review is not None
    assert status.pending_review.review_id == loaded.review_id
    assert status.pending_review.status.value == "stale"
    with pytest.raises(ApplicationError) as raised:
        await restarted.apply_review(loaded.review_id)
    assert raised.value.code is ApplicationErrorCode.REVIEW_STALE
    discarded = await restarted.discard_review(loaded.review_id)
    assert discarded.status == "discarded"
    assert destination.read_bytes() == b"external conflicting bytes\n"
    assert await restarted.get_pending_review() is None


async def test_review_can_be_discarded_by_exact_id(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None

    discarded = await application_with_pending_review.discard_review(pending.review_id)

    assert discarded.status == "discarded"
    assert discarded.review_id == pending.review_id
    assert await application_with_pending_review.get_pending_review() is None
