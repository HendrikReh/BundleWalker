# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Response
from starlette.testclient import TestClient

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel
from bundlewalker.application import ApplicationDependencies, WorkspaceApplication
from bundlewalker.domain import Citation, CitedAnswer
from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.security import BrowserSessionStore

BOOTSTRAP_SECRET = "correct-secret"
EXPECTED_HOST = "127.0.0.1:43123"


class _ReviewWebClient:
    def __init__(self, client: TestClient, csrf_token: str) -> None:
        self._client = client
        self.csrf_token = csrf_token

    def get(self, path: str) -> Response:
        return self._client.get(path)

    def post(self, path: str, **kwargs: Any) -> Response:
        return self._client.post(path, **kwargs)

    def post_json(self, path: str, body: object) -> Response:
        return self._client.post(
            path,
            json=body,
            headers={
                "Origin": f"http://{EXPECTED_HOST}",
                "X-BundleWalker-CSRF": self.csrf_token,
            },
        )


pytestmark = pytest.mark.usefixtures("application")


async def _query_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    question: str,
) -> tuple[CitedAnswer, frozenset[str]]:
    assert model == "test:model"
    assert question == "What do agents use?"
    dependencies.read_ids.add("topics/agents")
    return (
        CitedAnswer(
            title="Agent tools",
            body="# Agent tools\n\nAgents use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        frozenset({"topics/agents"}),
    )


def _application_with_runner(application: WorkspaceApplication) -> WorkspaceApplication:
    return WorkspaceApplication(
        application.workspace,
        ApplicationDependencies(
            environment={},
            query_runner=_query_runner,
            clock=lambda: datetime(2026, 7, 25, 13, tzinfo=UTC),
        ),
    )


@contextmanager
def _web_client(application: WorkspaceApplication) -> Generator[_ReviewWebClient]:
    sessions = BrowserSessionStore(BOOTSTRAP_SECRET)
    app = create_web_app(
        application,
        expected_host=EXPECTED_HOST,
        sessions=sessions,
    )
    with TestClient(app, base_url=f"http://{EXPECTED_HOST}") as test_client:
        response = test_client.get(
            f"/bootstrap?token={BOOTSTRAP_SECRET}",
            follow_redirects=False,
        )
        assert response.status_code == 303
        session = sessions.get(response.cookies["bundlewalker_session"])
        assert session is not None
        yield _ReviewWebClient(test_client, session.csrf_token)


async def _prepare_review(application: WorkspaceApplication):
    prepared = await _application_with_runner(application).prepare_synthesis(
        "What do agents use?",
        explicit_model="test:model",
    )
    return prepared.review


def test_get_review_returns_null_when_workspace_has_no_review(
    authenticated_client: Any,
) -> None:
    response = authenticated_client.get("/api/v1/review")

    assert response.status_code == 200
    assert response.json() is None


async def test_get_review_returns_the_exact_persisted_evidence(
    application: WorkspaceApplication,
) -> None:
    prepared = await _prepare_review(application)
    with _web_client(application) as client:
        response = client.get("/api/v1/review")

    assert response.status_code == 200
    assert response.json() == {
        "review_id": prepared.review_id,
        "kind": prepared.kind.value,
        "status": prepared.status.value,
        "summary": prepared.summary,
        "diff": prepared.diff,
        "changed_paths": list(prepared.changed_paths),
        "created_at": prepared.created_at.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("apply", "applied"), ("discard", "discarded")],
)
async def test_matching_review_id_resolves_once_and_reports_authoritative_status(
    application: WorkspaceApplication,
    action: str,
    expected_status: str,
) -> None:
    prepared = await _prepare_review(application)
    with _web_client(application) as client:
        response = client.post_json(
            f"/api/v1/reviews/{prepared.review_id}/{action}",
            {},
        )
        current = client.get("/api/v1/review")
        repeated = client.post_json(
            f"/api/v1/reviews/{prepared.review_id}/{action}",
            {},
        )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": prepared.review_id,
        "status": expected_status,
    }
    assert current.status_code == 200
    assert current.json() is None
    assert repeated.status_code == 404
    assert repeated.json()["error"]["code"] == "review_not_found"


async def test_wrong_route_id_does_not_resolve_the_authoritative_review(
    application: WorkspaceApplication,
) -> None:
    prepared = await _prepare_review(application)
    wrong_id = "0" * 32
    assert wrong_id != prepared.review_id
    with _web_client(application) as client:
        response = client.post_json(f"/api/v1/reviews/{wrong_id}/discard", {})
        current = client.get("/api/v1/review")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_id_mismatch"
    assert current.json()["review_id"] == prepared.review_id


async def test_stale_review_is_visible_rejected_for_apply_and_discardable(
    application: WorkspaceApplication,
) -> None:
    prepared = await _prepare_review(application)
    (application.workspace.wiki_dir / "external.md").write_text(
        "external edit\n",
        encoding="utf-8",
    )
    with _web_client(application) as client:
        shown = client.get("/api/v1/review")
        rejected = client.post_json(
            f"/api/v1/reviews/{prepared.review_id}/apply",
            {},
        )
        discarded = client.post_json(
            f"/api/v1/reviews/{prepared.review_id}/discard",
            {},
        )

    assert shown.json()["status"] == "stale"
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "review_stale"
    assert discarded.json()["status"] == "discarded"


async def test_review_mutations_require_origin_and_csrf(
    application: WorkspaceApplication,
) -> None:
    prepared = await _prepare_review(application)
    with _web_client(application) as client:
        missing_security = client.post(
            f"/api/v1/reviews/{prepared.review_id}/apply",
            headers={"Content-Type": "application/json"},
            content="{}",
        )
        wrong_origin = client.post(
            f"/api/v1/reviews/{prepared.review_id}/discard",
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:1",
                "X-BundleWalker-CSRF": client.csrf_token,
            },
            content="{}",
        )
        current = client.get("/api/v1/review")

    assert missing_security.status_code == 403
    assert wrong_origin.status_code == 403
    assert current.json()["review_id"] == prepared.review_id


async def test_mcp_prepared_review_is_resolved_through_web(
    application: WorkspaceApplication,
) -> None:
    mcp_application = _application_with_runner(application)
    prepared = await mcp_application.prepare_synthesis(
        "What do agents use?",
        explicit_model="test:model",
    )
    with _web_client(application) as client:
        shown = client.get("/api/v1/review").json()
        applied = client.post_json(
            f"/api/v1/reviews/{prepared.review.review_id}/apply",
            {},
        )

    assert shown["review_id"] == prepared.review.review_id
    assert applied.json()["status"] == "applied"
    assert await mcp_application.get_pending_review() is None
