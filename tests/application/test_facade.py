from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.application import (
    ApplicationDependencies,
    ApplicationError,
    ApplicationErrorCode,
    WorkspaceApplication,
)
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import get_pending_review
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

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
        ApplicationDependencies(environment={}, query_runner=_query_runner),
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
