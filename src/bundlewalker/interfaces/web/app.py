# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Secured Starlette shell for the local BundleWalker web interface."""

import mimetypes
import re
import secrets
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final

from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect, Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bundlewalker.application import WorkspaceApplication
from bundlewalker.interfaces.web.api import create_api_routes
from bundlewalker.interfaces.web.contracts import MAX_WEB_REQUEST_BYTES
from bundlewalker.interfaces.web.errors import unexpected_exception_handler
from bundlewalker.interfaces.web.security import BrowserSessionStore

SESSION_COOKIE_NAME: Final = "bundlewalker_session"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_HASHED_ASSET = re.compile(
    r"^[A-Za-z0-9_.]+-[A-Za-z0-9_-]{8,}\.(?:css|gif|ico|jpe?g|js|png|svg|webp|woff2?)$"
)
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def create_web_app(
    application: WorkspaceApplication,
    *,
    expected_host: str,
    sessions: BrowserSessionStore,
    static_dir: Traversable | None = None,
) -> Starlette:
    """Create one authenticated local web application."""
    packaged_static = static_dir or files("bundlewalker.interfaces.web").joinpath("static")

    async def bootstrap(request: Request) -> Response:
        session = sessions.exchange(request.query_params.get("token", ""))
        if session is None:
            return PlainTextResponse("Forbidden", status_code=403)
        response = RedirectResponse("/browse", status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    async def asset(request: Request) -> Response:
        asset_path = request.path_params["asset_path"]
        if not isinstance(asset_path, str) or _HASHED_ASSET.fullmatch(asset_path) is None:
            return PlainTextResponse("Not Found", status_code=404)
        candidate = packaged_static.joinpath("assets", asset_path)
        if not candidate.is_file():
            return PlainTextResponse("Not Found", status_code=404)
        media_type, _ = mimetypes.guess_type(asset_path)
        return Response(
            candidate.read_bytes(),
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def spa_shell(_: Request) -> Response:
        index = packaged_static.joinpath("index.html")
        if not index.is_file():
            return PlainTextResponse("Web interface assets are unavailable", status_code=500)
        return Response(index.read_bytes(), media_type="text/html")

    async def internal_error(request: Request, error: Exception) -> Response:
        response = await unexpected_exception_handler(request, error)
        _apply_security_headers(response.headers)
        return response

    routes = [
        Route("/bootstrap", bootstrap, methods=["GET"]),
        *create_api_routes(application),
        Route("/assets/{asset_path:path}", asset, methods=["GET"]),
        Route("/browse", spa_shell, methods=["GET"]),
        Route("/browse/{concept_id:path}", spa_shell, methods=["GET"]),
        Route("/ask", spa_shell, methods=["GET"]),
        Route("/lint", spa_shell, methods=["GET"]),
        Route("/ingest", spa_shell, methods=["GET"]),
        Route("/review/{review_id}", spa_shell, methods=["GET"]),
    ]
    app = Starlette(
        routes=routes,
        exception_handlers={Exception: internal_error},
    )
    app.state.application = application
    app.state.sessions = sessions
    app.add_middleware(
        WebSecurityMiddleware,
        expected_host=expected_host,
        sessions=sessions,
    )
    return app


class WebSecurityMiddleware:
    """Enforce local browser authentication before routing requests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        expected_host: str,
        sessions: BrowserSessionStore,
    ) -> None:
        self._app = app
        self._expected_host = expected_host
        self._expected_origin = f"http://{expected_host}"
        self._sessions = sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        send_hardened = self._hardened_send(send)
        if headers.get("host") != self._expected_host:
            await _error_response(403, scope, receive, send_hardened)
            return

        session = None
        if scope["path"] != "/bootstrap":
            request = Request(scope)
            session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
            session = self._sessions.get(session_id)
            if session is None:
                await _error_response(403, scope, receive, send_hardened)
                return

        replay_receive = receive
        if scope["path"] != "/bootstrap" and scope["method"].upper() in _MUTATING_METHODS:
            assert session is not None
            csrf_token = headers.get("x-bundlewalker-csrf", "")
            if headers.get("origin") != self._expected_origin or not secrets.compare_digest(
                csrf_token, session.csrf_token
            ):
                await _error_response(403, scope, receive, send_hardened)
                return
            content_type = headers.get("content-type", "").partition(";")[0].strip().lower()
            if content_type != "application/json":
                await _error_response(415, scope, receive, send_hardened)
                return
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_WEB_REQUEST_BYTES:
                        await _error_response(413, scope, receive, send_hardened)
                        return
                except ValueError:
                    await _error_response(400, scope, receive, send_hardened)
                    return
            try:
                body = await _read_bounded_body(receive)
            except ClientDisconnect:
                return
            if body is None:
                await _error_response(413, scope, receive, send_hardened)
                return
            replay_receive = _replay_body(body)

        await self._app(scope, replay_receive, send_hardened)

    def _hardened_send(self, send: Send) -> Send:
        async def send_hardened(message: Message) -> None:
            if message["type"] == "http.response.start":
                _apply_security_headers(MutableHeaders(scope=message))
            await send(message)

        return send_hardened


def _apply_security_headers(headers: MutableHeaders) -> None:
    headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    if "cache-control" not in headers:
        headers["Cache-Control"] = "no-store"


async def _error_response(
    status_code: int,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response = PlainTextResponse(
        {
            400: "Bad Request",
            403: "Forbidden",
            413: "Content Too Large",
            415: "Unsupported Media Type",
        }[status_code],
        status_code=status_code,
    )
    await response(scope, receive, send)


async def _read_bounded_body(receive: Receive) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnect
        body = message.get("body", b"")
        size += len(body)
        if size > MAX_WEB_REQUEST_BYTES:
            return None
        chunks.append(body)
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay_body(body: bytes) -> Receive:
    consumed = False

    async def receive() -> Message:
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive
