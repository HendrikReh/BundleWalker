# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authenticated synthesis and refresh preparation API coverage."""

from datetime import UTC, datetime
from typing import Protocol

import pytest
from httpx2 import Response

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.application import (
    MAX_QUESTION_CHARACTERS,
    ApplicationDependencies,
    WorkspaceApplication,
)
from bundlewalker.domain import Citation, CitedAnswer, OkfDocument, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


class AuthenticatedWebClient(Protocol):
    def get(self, path: str) -> Response: ...

    def post_json(self, path: str, body: object) -> Response: ...


def _answer(
    *,
    title: str = "Agent tools",
    body: str = "# Answer\n\nAgents can use tools [1].\n",
) -> CitedAnswer:
    return CitedAnswer(
        title=title,
        body=body,
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


def _write_refresh_target(
    application: WorkspaceApplication,
    *,
    concept_id: str = "syntheses/agent-framework",
    concept_type: str = "Synthesis",
) -> None:
    path = application.workspace.wiki_dir / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_document(
            OkfMetadata(
                type=concept_type,
                title="Agent framework",
                description="A maintained agent framework.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Agent framework\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(application.workspace.wiki_dir)


async def _current_refresh_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    instruction: str,
    target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert instruction == "Check current evidence"
    assert target.concept_id == "syntheses/agent-framework"
    dependencies.read_ids.add("topics/agents")
    return (
        _answer(
            title="Agent framework",
            body="# Agent framework\n\nAgents can use tools [1].\n",
        ),
        frozenset({"topics/agents"}),
    )


async def _pending_refresh_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    instruction: str,
    target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert instruction == "Add current evidence"
    assert target.concept_id == "syntheses/agent-framework"
    dependencies.read_ids.add("topics/agents")
    return (
        _answer(
            title="Updated agent framework",
            body="# Updated framework\n\nCurrent evidence still supports tool use [1].\n",
        ),
        frozenset({"topics/agents"}),
    )


async def test_synthesis_is_a_separate_model_call_with_a_mandatory_review(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls: list[str] = []

    async def runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        calls.append(question)
        return await _query_runner(model, dependencies, question)

    application.dependencies = ApplicationDependencies(
        environment={},
        query_runner=runner,
        clock=lambda: NOW,
    )

    asked = authenticated_client.post_json(
        "/api/v1/ask",
        {"question": "What do agents use?", "model": "test:model"},
    )
    assert asked.status_code == 200
    assert await application.get_pending_review() is None

    prepared = authenticated_client.post_json(
        "/api/v1/syntheses",
        {"question": "What do agents use?", "model": "test:model"},
    )

    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    pending = await application.get_pending_review()
    assert pending is not None
    assert calls == ["What do agents use?", "What do agents use?"]
    assert body["answer"]["title"] == "Agent tools"
    assert body["review"]["review_id"] == pending.review_id
    assert body["review"]["kind"] == "synthesis"
    assert "answer" not in prepared.request.content.decode()


async def test_synthesis_pending_conflict_precedes_provider_work(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
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

    application.dependencies = ApplicationDependencies(
        environment={},
        query_runner=runner,
        clock=lambda: NOW,
    )
    first = authenticated_client.post_json(
        "/api/v1/syntheses",
        {"question": "What do agents use?", "model": "test:model"},
    )
    assert first.status_code == 200, first.text

    blocked = authenticated_client.post_json(
        "/api/v1/syntheses",
        {"question": "What do agents use?", "model": "test:model"},
    )

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "review_pending"
    assert calls == 1


async def test_refresh_current_returns_answer_without_creating_review(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    _write_refresh_target(application)
    application.dependencies = ApplicationDependencies(
        environment={},
        refresh_runner=_current_refresh_runner,
        clock=lambda: NOW,
    )

    response = authenticated_client.post_json(
        "/api/v1/refreshes",
        {
            "instruction": "Check current evidence",
            "concept_id": "syntheses/agent-framework",
            "model": "test:model",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "current",
        "concept_id": "syntheses/agent-framework",
        "answer": {
            "title": "Agent framework",
            "markdown": (
                "# Agent framework\n\nAgents can use tools [1].\n\n"
                "# Citations\n\n[1] [Agents](/topics/agents.md)\n"
            ),
            "citations": [{"number": 1, "concept_id": "topics/agents"}],
        },
        "review": None,
    }
    assert await application.get_pending_review() is None


async def test_refresh_pending_returns_answer_and_exact_review(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    _write_refresh_target(application)
    application.dependencies = ApplicationDependencies(
        environment={},
        refresh_runner=_pending_refresh_runner,
        clock=lambda: NOW,
    )

    response = authenticated_client.post_json(
        "/api/v1/refreshes",
        {
            "instruction": "Add current evidence",
            "concept_id": "syntheses/agent-framework",
            "model": "test:model",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    pending = await application.get_pending_review()
    assert pending is not None
    assert body["status"] == "pending"
    assert body["concept_id"] == "syntheses/agent-framework"
    assert body["answer"]["title"] == "Updated agent framework"
    assert body["review"]["review_id"] == pending.review_id
    assert body["review"]["kind"] == "refresh"


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "instruction": "",
                "concept_id": "syntheses/agent-framework",
                "model": "test:model",
            },
            "request body does not match the expected JSON contract",
        ),
        (
            {
                "instruction": "x" * (MAX_QUESTION_CHARACTERS + 1),
                "concept_id": "syntheses/agent-framework",
                "model": "test:model",
            },
            "request body does not match the expected JSON contract",
        ),
        (
            {
                "instruction": "Refresh",
                "concept_id": "../private",
                "model": "test:model",
            },
            "refresh target must be a canonical Synthesis concept ID",
        ),
    ],
    ids=["empty-instruction", "oversized-instruction", "invalid-concept-id"],
)
async def test_refresh_rejects_invalid_input_without_provider_work_or_leakage(
    payload: dict[str, object],
    expected_message: str,
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls = 0

    async def runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _instruction: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid refresh reached the provider")

    application.dependencies = ApplicationDependencies(
        environment={},
        refresh_runner=runner,
    )

    response = authenticated_client.post_json("/api/v1/refreshes", payload)

    assert response.status_code == 422
    assert response.json()["error"]["message"] == expected_message
    assert "../private" not in response.text
    assert calls == 0


async def test_refresh_preserves_non_synthesis_application_error(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    _write_refresh_target(
        application,
        concept_id="syntheses/not-generated",
        concept_type="Topic",
    )
    application.dependencies = ApplicationDependencies(environment={})

    response = authenticated_client.post_json(
        "/api/v1/refreshes",
        {
            "instruction": "Refresh",
            "concept_id": "syntheses/not-generated",
            "model": "test:model",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "refresh target is not a Synthesis"
    assert "syntheses/not-generated" not in response.text


async def test_refresh_pending_conflict_precedes_provider_work_for_valid_target(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    _write_refresh_target(application)
    application.dependencies = ApplicationDependencies(
        environment={},
        query_runner=_query_runner,
        clock=lambda: NOW,
    )
    prepared = authenticated_client.post_json(
        "/api/v1/syntheses",
        {"question": "What do agents use?", "model": "test:model"},
    )
    assert prepared.status_code == 200, prepared.text
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _instruction: str,
        _target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("pending refresh reached the provider")

    application.dependencies = ApplicationDependencies(
        environment={},
        refresh_runner=must_not_run,
    )

    response = authenticated_client.post_json(
        "/api/v1/refreshes",
        {
            "instruction": "Add current evidence",
            "concept_id": "syntheses/agent-framework",
            "model": "test:model",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_pending"
    assert calls == 0


def test_refresh_client_route_serves_authenticated_spa_shell(
    authenticated_client: AuthenticatedWebClient,
) -> None:
    response = authenticated_client.get("/refresh/syntheses/agent-framework")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
