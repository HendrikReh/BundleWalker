# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loopback server lifecycle tests."""

from collections.abc import Callable
from io import StringIO
from pathlib import Path
from socket import create_connection, socket

import pytest
from starlette.applications import Starlette

from bundlewalker.application import ApplicationError, ApplicationErrorCode
from bundlewalker.interfaces.web import server as server_module
from bundlewalker.interfaces.web.security import BrowserSessionStore
from bundlewalker.interfaces.web.server import bind_loopback_socket, main, serve_web
from bundlewalker.workspace import Workspace, discover_workspace, initialize_workspace


class FakeServer:
    def __init__(self, app: Starlette, events: list[str]) -> None:
        self.app = app
        self.events = events
        self.sockets: list[socket] = []
        self.addresses: list[tuple[str, int]] = []

    async def serve(self, sockets: list[socket]) -> None:
        self.events.append("serve")
        self.sockets = sockets
        self.addresses = [item.getsockname() for item in sockets]


def _server_factory(
    events: list[str],
    servers: list[FakeServer],
) -> Callable[[Starlette], FakeServer]:
    def create(app: Starlette) -> FakeServer:
        server = FakeServer(app, events)
        servers.append(server)
        return server

    return create


def test_bind_loopback_socket_uses_ephemeral_ipv4_port() -> None:
    listener = bind_loopback_socket()
    try:
        host, port = listener.getsockname()
        assert host == "127.0.0.1"
        assert port != 0
        with create_connection((host, port), timeout=1):
            pass
    finally:
        listener.close()


async def test_serve_web_discovers_explicit_workspace_before_opening_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    events: list[str] = []
    servers: list[FakeServer] = []

    def tracked_discovery(path: Path | None) -> Workspace:
        events.append("discover")
        return discover_workspace(path)

    def browser_opener(_: str) -> bool:
        events.append("open")
        return True

    monkeypatch.setattr(server_module, "discover_workspace", tracked_discovery)

    await serve_web(
        workspace.root,
        browser_opener=browser_opener,
        server_factory=_server_factory(events, servers),
    )

    assert events == ["discover", "open", "serve"]
    assert servers[0].app.state.application.workspace.root == workspace.root
    assert servers[0].sockets[0].fileno() == -1


async def test_browser_open_failure_prints_complete_url_and_still_serves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    events: list[str] = []
    servers: list[FakeServer] = []
    error_output = StringIO()

    def fixed_token_urlsafe(_: int) -> str:
        return "startup-secret"

    monkeypatch.setattr(server_module.secrets, "token_urlsafe", fixed_token_urlsafe)

    await serve_web(
        workspace.root,
        browser_opener=lambda _: False,
        error_output=error_output,
        server_factory=_server_factory(events, servers),
    )

    listener_host, listener_port = servers[0].addresses[0]
    assert error_output.getvalue() == (
        f"Open this URL in your browser: "
        f"http://{listener_host}:{listener_port}/bootstrap?token=startup-secret\n"
    )
    assert events == ["serve"]


async def test_shutdown_clears_browser_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    events: list[str] = []
    servers: list[FakeServer] = []
    stores: list[BrowserSessionStore] = []

    class RecordingSessionStore(BrowserSessionStore):
        def __init__(self, bootstrap_secret: str) -> None:
            super().__init__(bootstrap_secret)
            self.cleared = False
            stores.append(self)

        def clear(self) -> None:
            self.cleared = True
            super().clear()

    monkeypatch.setattr(server_module, "BrowserSessionStore", RecordingSessionStore)

    await serve_web(
        workspace.root,
        browser_opener=lambda _: True,
        server_factory=_server_factory(events, servers),
    )

    assert isinstance(stores[0], RecordingSessionStore)
    assert stores[0].cleared is True


async def test_startup_secret_failure_closes_bound_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    listener = bind_loopback_socket()

    def bound_listener() -> socket:
        return listener

    def fail_token_urlsafe(_: int) -> str:
        raise RuntimeError("secret generation failed")

    monkeypatch.setattr(server_module, "bind_loopback_socket", bound_listener)
    monkeypatch.setattr(server_module.secrets, "token_urlsafe", fail_token_urlsafe)

    with pytest.raises(RuntimeError, match="secret generation failed"):
        await serve_web(workspace.root, browser_opener=lambda _: True)

    assert listener.fileno() == -1


async def test_invalid_assets_fail_before_binding_or_opening_or_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    events: list[str] = []

    def reject_assets() -> None:
        events.append("validate")
        raise ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            "web interface assets are unavailable",
        )

    def unexpected_bind() -> socket:
        events.append("bind")
        raise AssertionError("listener must not be bound")

    def unexpected_open(_: str) -> bool:
        events.append("open")
        raise AssertionError("browser must not be opened")

    def unexpected_server(_: Starlette) -> FakeServer:
        events.append("server")
        raise AssertionError("server must not be created")

    monkeypatch.setattr(server_module, "validate_web_assets", reject_assets, raising=False)
    monkeypatch.setattr(server_module, "bind_loopback_socket", unexpected_bind)

    with pytest.raises(ApplicationError, match="web interface assets are unavailable"):
        await serve_web(
            workspace.root,
            browser_opener=unexpected_open,
            server_factory=unexpected_server,
        )

    assert events == ["validate"]


def test_main_prints_only_bounded_workspace_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--workspace", str(tmp_path / "missing")])

    assert raised.value.code == 1
    assert capsys.readouterr().err == "Error: workspace operation failed\n"


def test_main_prints_only_bounded_web_asset_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    private_path = tmp_path / "private" / "manifest.json"

    def reject_assets() -> None:
        try:
            raise OSError(f"could not read {private_path}")
        except OSError as error:
            raise ApplicationError(
                ApplicationErrorCode.CONFIGURATION_ERROR,
                "web interface assets are unavailable",
            ) from error

    def unexpected_bind() -> socket:
        raise AssertionError("listener must not be bound")

    monkeypatch.setattr(server_module, "validate_web_assets", reject_assets)
    monkeypatch.setattr(server_module, "bind_loopback_socket", unexpected_bind)

    with pytest.raises(SystemExit) as raised:
        main(["--workspace", str(workspace.root)])

    assert raised.value.code == 1
    error_output = capsys.readouterr().err
    assert error_output == "Error: web interface assets are unavailable\n"
    assert str(private_path) not in error_output


def test_main_bounds_unexpected_socket_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    private_path = tmp_path / "private" / "socket"

    def fail_bind() -> socket:
        raise OSError(f"could not bind {private_path}")

    monkeypatch.setattr(server_module, "bind_loopback_socket", fail_bind)

    with pytest.raises(SystemExit) as raised:
        main(["--workspace", str(workspace.root)])

    assert raised.value.code == 1
    error_output = capsys.readouterr().err
    assert error_output == "Error: local web server failed\n"
    assert str(private_path) not in error_output


def test_main_bounds_unexpected_server_failure_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = initialize_workspace(tmp_path / "workspace")
    private_path = tmp_path / "private" / "uvicorn.log"
    listener = socket()

    class RecordingSessionStore(BrowserSessionStore):
        def __init__(self, bootstrap_secret: str) -> None:
            super().__init__(bootstrap_secret)
            self.cleared = False
            stores.append(self)

        def clear(self) -> None:
            self.cleared = True
            super().clear()

    stores: list[RecordingSessionStore] = []

    class FailingServer:
        async def serve(self, sockets: list[socket]) -> None:
            assert sockets == [listener]
            raise RuntimeError(f"server failed at {private_path}")

    def bind_listener() -> socket:
        return listener

    def browser_opener(_: str) -> bool:
        return True

    def create_server(_: Starlette) -> FailingServer:
        return FailingServer()

    monkeypatch.setattr(server_module, "bind_loopback_socket", bind_listener)
    monkeypatch.setattr(server_module, "BrowserSessionStore", RecordingSessionStore)
    monkeypatch.setattr(server_module.webbrowser, "open", browser_opener)
    monkeypatch.setattr(server_module, "_create_uvicorn_server", create_server)

    with pytest.raises(SystemExit) as raised:
        main(["--workspace", str(workspace.root)])

    assert raised.value.code == 1
    error_output = capsys.readouterr().err
    assert error_output == "Error: local web server failed\n"
    assert str(private_path) not in error_output
    assert listener.fileno() == -1
    assert stores[0].cleared is True
