"""Simple dashboard unlock token (APP_PASSWORD, default alphafx)."""

from __future__ import annotations

import os
import secrets
import threading

_lock = threading.Lock()
_sessions: set[str] = set()


def app_password() -> str:
    return os.environ.get("APP_PASSWORD", "alphafx").strip() or "alphafx"


def verify_password(password: str) -> bool:
    return secrets.compare_digest(password.strip(), app_password())


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions.add(token)
        if len(_sessions) > 500:
            _sessions.clear()
            _sessions.add(token)
    return token


def verify_session(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        return token in _sessions


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        _sessions.discard(token)
