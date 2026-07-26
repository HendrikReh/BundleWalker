# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared fixtures for the local web interface."""

from collections.abc import Generator, Mapping
from pathlib import Path

import pytest
from httpx2 import Response
from starlette.testclient import TestClient

from bundlewalker.application import WorkspaceApplication
from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.security import BrowserSessionStore
from bundlewalker.workspace import initialize_workspace

BOOTSTRAP_SECRET = "correct-secret"
EXPECTED_HOST = "127.0.0.1:43123"
EXPECTED_ORIGIN = f"http://{EXPECTED_HOST}"


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
    return WorkspaceApplication(initialize_workspace(tmp_path / "workspace"))


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
