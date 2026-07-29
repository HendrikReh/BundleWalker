# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""In-memory browser bootstrap and session state."""

import hashlib
import secrets
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class BrowserSession:
    """One process-local browser session and its independent CSRF credential."""

    session_id: str
    csrf_token: str


class BrowserSessionStore:
    """Exchange one bootstrap secret and retain only process-local sessions."""

    def __init__(self, bootstrap_secret: str) -> None:
        self._bootstrap_digest: bytes | None = _digest(bootstrap_secret)
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = Lock()

    def exchange(self, candidate: str) -> BrowserSession | None:
        """Exchange the single-use bootstrap value for a new browser session."""
        candidate_digest = _digest(candidate)
        with self._lock:
            expected_digest = self._bootstrap_digest
            if expected_digest is None or not secrets.compare_digest(
                candidate_digest,
                expected_digest,
            ):
                return None
            self._bootstrap_digest = None
            session = BrowserSession(
                session_id=secrets.token_urlsafe(32),
                csrf_token=secrets.token_urlsafe(32),
            )
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> BrowserSession | None:
        """Return a current browser session without extending its lifetime."""
        with self._lock:
            return self._sessions.get(session_id)

    def clear(self) -> None:
        """Invalidate the bootstrap exchange and every browser session."""
        with self._lock:
            self._bootstrap_digest = None
            self._sessions.clear()


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()
