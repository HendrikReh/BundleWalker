# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Secure local web interface."""

from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.security import BrowserSession, BrowserSessionStore
from bundlewalker.interfaces.web.server import bind_loopback_socket, serve_web

__all__ = [
    "BrowserSession",
    "BrowserSessionStore",
    "bind_loopback_socket",
    "create_web_app",
    "serve_web",
]
