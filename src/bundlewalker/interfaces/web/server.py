# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loopback-only Uvicorn lifecycle and command entry point."""

import argparse
import asyncio
import secrets
import socket
import sys
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, TextIO, cast

import uvicorn
from starlette.applications import Starlette

from bundlewalker.application import ApplicationError, WorkspaceApplication, translate_error
from bundlewalker.errors import BundleWalkerError
from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.assets import validate_web_assets
from bundlewalker.interfaces.web.security import BrowserSessionStore
from bundlewalker.workspace import discover_workspace

LOOPBACK_HOST = "127.0.0.1"


class WebServer(Protocol):
    """The Uvicorn surface needed by the process lifecycle."""

    async def serve(self, sockets: list[socket.socket]) -> None: ...


BrowserOpener = Callable[[str], bool]
ServerFactory = Callable[[Starlette], WebServer]


def bind_loopback_socket() -> socket.socket:
    """Pre-bind an operating-system-selected IPv4 loopback port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((LOOPBACK_HOST, 0))
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


async def serve_web(
    workspace_path: Path | None = None,
    *,
    browser_opener: BrowserOpener | None = None,
    error_output: TextIO | None = None,
    server_factory: ServerFactory | None = None,
) -> None:
    """Discover one workspace and serve it through one local browser session."""
    workspace = discover_workspace(workspace_path)
    application = WorkspaceApplication(workspace)
    web_assets = validate_web_assets()
    listener = bind_loopback_socket()
    sessions: BrowserSessionStore | None = None
    try:
        bootstrap_secret = secrets.token_urlsafe(32)
        sessions = BrowserSessionStore(bootstrap_secret)
        host, port = cast(tuple[str, int], listener.getsockname())
        expected_host = f"{host}:{port}"
        app = create_web_app(
            application,
            expected_host=expected_host,
            sessions=sessions,
            web_assets=web_assets,
        )
        server = (server_factory or _create_uvicorn_server)(app)
        bootstrap_url = f"http://{expected_host}/bootstrap?token={bootstrap_secret}"
        open_browser = browser_opener or webbrowser.open
        stderr = error_output if error_output is not None else sys.stderr
        try:
            opened = open_browser(bootstrap_url)
        except Exception:
            opened = False
        if not opened:
            print(f"Open this URL in your browser: {bootstrap_url}", file=stderr)
        await server.serve(sockets=[listener])
    finally:
        if sessions is not None:
            sessions.clear()
        listener.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run one web server bound to one discovered workspace."""
    parser = argparse.ArgumentParser(prog="bundlewalker-web")
    parser.add_argument("--workspace", type=Path)
    arguments = parser.parse_args(argv)
    try:
        asyncio.run(serve_web(arguments.workspace))
    except BundleWalkerError as error:
        print(f"Error: {translate_error(error).safe_message}", file=sys.stderr)
        raise SystemExit(error.exit_code) from None
    except ApplicationError as error:
        print(f"Error: {error.safe_message}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Error: local web server failed", file=sys.stderr)
        raise SystemExit(1) from None


def _create_uvicorn_server(app: Starlette) -> WebServer:
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=0,
        access_log=False,
    )
    return uvicorn.Server(config)
