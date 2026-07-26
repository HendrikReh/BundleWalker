# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared fixtures for the local web interface."""

from collections.abc import Generator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx2 import Response
from starlette.testclient import TestClient

from bundlewalker.application import WorkspaceApplication
from bundlewalker.domain import OkfMetadata
from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.security import BrowserSessionStore
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workspace import initialize_workspace

BOOTSTRAP_SECRET = "correct-secret"
EXPECTED_HOST = "127.0.0.1:43123"
EXPECTED_ORIGIN = f"http://{EXPECTED_HOST}"
NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


class AuthenticatedWebClient:
    """A test client with one bootstrapped browser session."""

    def __init__(
        self,
        client: TestClient,
        sessions: BrowserSessionStore,
        bootstrap_secret: str,
    ) -> None:
        response = client.get(
            f"/bootstrap?token={bootstrap_secret}",
            follow_redirects=False,
        )
        assert response.status_code == 303
        session_id = response.cookies["bundlewalker_session"]
        session = sessions.get(session_id)
        assert session is not None
        self._client = client
        self.csrf_token = session.csrf_token
        self.expected_origin = EXPECTED_ORIGIN

    def get(self, path: str) -> Response:
        return self._client.get(path)

    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> Response:
        return self._client.post(path, headers=headers, content=content)

    def post_json(self, path: str, body: object) -> Response:
        return self._client.post(
            path,
            json=body,
            headers={
                "Host": EXPECTED_HOST,
                "Origin": self.expected_origin,
                "X-BundleWalker-CSRF": self.csrf_token,
            },
        )


@pytest.fixture
def sessions() -> BrowserSessionStore:
    return BrowserSessionStore(BOOTSTRAP_SECRET)


@pytest.fixture
def application(tmp_path: Path) -> WorkspaceApplication:
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
            OkfMetadata(
                type="Entity",
                title="Tools",
                description="Tools support agent workflows.",
                tags=["tools"],
                timestamp=NOW,
            ),
            "# Tools\n\nTools support agent workflows.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return WorkspaceApplication(workspace)


@pytest.fixture
def client(
    application: WorkspaceApplication,
    sessions: BrowserSessionStore,
) -> Generator[TestClient]:
    app = create_web_app(
        application,
        expected_host=EXPECTED_HOST,
        sessions=sessions,
    )
    with TestClient(app, base_url=EXPECTED_ORIGIN) as test_client:
        yield test_client


@pytest.fixture
def authenticated_client(
    application: WorkspaceApplication,
    sessions: BrowserSessionStore,
) -> Generator[AuthenticatedWebClient]:
    app = create_web_app(
        application,
        expected_host=EXPECTED_HOST,
        sessions=sessions,
    )
    with TestClient(app, base_url=EXPECTED_ORIGIN) as test_client:
        yield AuthenticatedWebClient(test_client, sessions, BOOTSTRAP_SECRET)
