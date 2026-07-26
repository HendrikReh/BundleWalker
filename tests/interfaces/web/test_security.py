# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Security boundary tests for the local web interface."""

from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Protocol

import pytest
from httpx2 import Response
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from bundlewalker.application import WorkspaceApplication
from bundlewalker.interfaces.web.app import (
    MAX_WEB_REQUEST_BYTES,
    WebSecurityMiddleware,
    create_web_app,
)
from bundlewalker.interfaces.web.security import BrowserSessionStore

EXPECTED_HOST = "127.0.0.1:43123"


class AuthenticatedClient(Protocol):
    csrf_token: str
    expected_origin: str

    def get(self, path: str) -> Response: ...

    def post(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> Response: ...

    def post_json(self, path: str, body: object) -> Response: ...


def test_session_store_exchanges_bootstrap_once_and_clears_sessions() -> None:
    sessions = BrowserSessionStore("correct-secret")

    assert sessions.exchange("wrong-secret") is None
    first = sessions.exchange("correct-secret")
    assert first is not None
    assert first.session_id != first.csrf_token
    assert len(first.session_id) >= 43
    assert len(first.csrf_token) >= 43
    assert sessions.get(first.session_id) == first
    assert sessions.exchange("correct-secret") is None

    sessions.clear()

    assert sessions.get(first.session_id) is None


def test_bootstrap_is_single_use_and_redirects_to_clean_browse_url(
    client: TestClient,
) -> None:
    response = client.get("/bootstrap?token=correct-secret", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/browse"
    assert "bundlewalker_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert "Path=/" in response.headers["set-cookie"]
    assert client.get("/bootstrap?token=correct-secret").status_code == 403


def test_bootstrap_rejects_missing_or_invalid_secret(client: TestClient) -> None:
    assert client.get("/bootstrap").status_code == 403
    assert client.get("/bootstrap?token=wrong-secret").status_code == 403


def test_routes_reject_unsupported_methods_without_server_errors(
    client: TestClient,
    authenticated_client: AuthenticatedClient,
) -> None:
    assert client.post("/bootstrap").status_code == 405
    assert authenticated_client.post_json("/api/v1/workspace", {}).status_code == 405


def test_every_request_requires_the_exact_host_and_port(client: TestClient) -> None:
    assert (
        client.get(
            "/bootstrap?token=correct-secret",
            headers={"Host": "localhost:43123"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/bootstrap?token=correct-secret",
            headers={"Host": "127.0.0.1:43124"},
        ).status_code
        == 403
    )


def test_protected_routes_require_a_browser_session(client: TestClient) -> None:
    asset_name = next(
        asset.name
        for asset in files("bundlewalker.interfaces.web").joinpath("static", "assets").iterdir()
        if asset.name.endswith(".js")
    )

    assert client.get("/browse").status_code == 403
    assert client.get("/api/v1/workspace").status_code == 403
    assert client.get(f"/assets/{asset_name}").status_code == 403


def test_mutation_requires_exact_origin_and_csrf(
    authenticated_client: AuthenticatedClient,
) -> None:
    assert authenticated_client.post("/api/v1/workspace").status_code == 403
    assert (
        authenticated_client.post(
            "/api/v1/workspace",
            headers={
                "Origin": authenticated_client.expected_origin,
                "X-BundleWalker-CSRF": "wrong-token",
                "Content-Type": "application/json",
            },
            content=b"{}",
        ).status_code
        == 403
    )
    assert (
        authenticated_client.post(
            "/api/v1/workspace",
            headers={
                "Origin": "http://localhost:43123",
                "X-BundleWalker-CSRF": authenticated_client.csrf_token,
                "Content-Type": "application/json",
            },
            content=b"{}",
        ).status_code
        == 403
    )
    assert authenticated_client.post_json("/api/v1/workspace", {}).status_code == 405


def test_mutation_rejects_unsupported_content_type(
    authenticated_client: AuthenticatedClient,
) -> None:
    response = authenticated_client.post(
        "/api/v1/workspace",
        headers={
            "Origin": authenticated_client.expected_origin,
            "X-BundleWalker-CSRF": authenticated_client.csrf_token,
            "Content-Type": "text/plain",
        },
        content="{}",
    )

    assert response.status_code == 415


def test_mutation_rejects_excessive_request_body(
    authenticated_client: AuthenticatedClient,
) -> None:
    response = authenticated_client.post(
        "/api/v1/workspace",
        headers={
            "Origin": authenticated_client.expected_origin,
            "X-BundleWalker-CSRF": authenticated_client.csrf_token,
            "Content-Type": "application/json",
        },
        content=b"x" * (MAX_WEB_REQUEST_BYTES + 1),
    )

    assert response.status_code == 413


async def test_mutation_disconnect_does_not_dispatch_downstream() -> None:
    sessions = BrowserSessionStore("correct-secret")
    session = sessions.exchange("correct-secret")
    assert session is not None
    downstream_called = False

    async def downstream(_: Scope, __: Receive, ___: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    middleware = WebSecurityMiddleware(
        downstream,
        expected_host=EXPECTED_HOST,
        sessions=sessions,
    )
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "server": ("127.0.0.1", 43123),
        "client": ("127.0.0.1", 50000),
        "scheme": "http",
        "method": "POST",
        "root_path": "",
        "path": "/api/v1/workspace",
        "raw_path": b"/api/v1/workspace",
        "query_string": b"",
        "headers": [
            (b"host", EXPECTED_HOST.encode("ascii")),
            (b"origin", f"http://{EXPECTED_HOST}".encode("ascii")),
            (b"x-bundlewalker-csrf", session.csrf_token.encode("ascii")),
            (b"content-type", b"application/json"),
            (b"content-length", b"2"),
            (b"cookie", f"bundlewalker_session={session.session_id}".encode("ascii")),
        ],
        "state": {},
    }
    incoming: list[Message] = [
        {"type": "http.request", "body": b"{", "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(scope, receive, send)

    assert downstream_called is False
    assert sent == []


def test_responses_include_browser_security_headers(client: TestClient) -> None:
    response = client.get("/browse")

    assert response.status_code == 403
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_unexpected_error_response_includes_browser_security_headers(
    application: WorkspaceApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("shell", encoding="utf-8")
    sessions = BrowserSessionStore("correct-secret")
    app = create_web_app(
        application,
        expected_host=EXPECTED_HOST,
        sessions=sessions,
        static_dir=static_dir,
    )

    def fail_read_bytes(_: Path) -> bytes:
        raise OSError("simulated asset read failure")

    with TestClient(
        app,
        base_url=f"http://{EXPECTED_HOST}",
        raise_server_exceptions=False,
    ) as test_client:
        bootstrap = test_client.get(
            "/bootstrap?token=correct-secret",
            follow_redirects=False,
        )
        assert bootstrap.status_code == 303
        monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
        response = test_client.get("/browse")

    assert response.status_code == 500
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_html_and_api_are_not_cached_but_hashed_assets_are_immutable(
    authenticated_client: AuthenticatedClient,
) -> None:
    asset_name = next(
        asset.name
        for asset in files("bundlewalker.interfaces.web").joinpath("static", "assets").iterdir()
        if asset.name.endswith(".js")
    )

    html = authenticated_client.get("/browse")
    api = authenticated_client.get("/api/v1/workspace")
    asset = authenticated_client.get(f"/assets/{asset_name}")

    assert html.status_code == 200
    assert html.headers["cache-control"] == "no-store"
    assert api.status_code == 200
    assert api.headers["cache-control"] == "no-store"
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_only_recognized_spa_routes_serve_the_shell(
    authenticated_client: AuthenticatedClient,
) -> None:
    assert authenticated_client.get("/browse/topics/agents").status_code == 200
    assert authenticated_client.get("/ask").status_code == 200
    assert authenticated_client.get(f"/review/{'a' * 32}").status_code == 200
    assert authenticated_client.get("/unknown").status_code == 404
