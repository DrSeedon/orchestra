"""Dashboard authentication — cookie-based sessions from .env credentials."""

import hmac
import os
import time
from uuid import uuid4

SESSION_TTL = 86400

_sessions: dict[str, dict] = {}


def is_auth_enabled() -> bool:
    return bool(os.environ.get("DASHBOARD_USER") and os.environ.get("DASHBOARD_PASSWORD"))


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("DASHBOARD_USER", "")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    return (
        hmac.compare_digest(username.encode(), expected_user.encode())
        and hmac.compare_digest(password.encode(), expected_pass.encode())
    )


def create_session(username: str) -> str:
    token = uuid4().hex
    _sessions[token] = {"user": username, "created_at": time.time()}
    return token


def validate_session(token: str) -> bool:
    if not token:
        return False
    session = _sessions.get(token)
    if not session:
        return False
    if time.time() - session["created_at"] > SESSION_TTL:
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: str) -> None:
    _sessions.pop(token, None)


def cleanup_expired() -> None:
    now = time.time()
    expired = [t for t, s in _sessions.items() if now - s["created_at"] > SESSION_TTL]
    for t in expired:
        del _sessions[t]


def check_internal_token(auth_header: str) -> bool:
    token = os.environ.get("INTERNAL_TOKEN", "")
    if not token:
        return True
    if not auth_header:
        return False
    return hmac.compare_digest(auth_header.encode(), f"Bearer {token}".encode())


def requires_auth(path: str, method: str) -> bool:
    if path in ("/login", "/logout"):
        return False
    if path.startswith(("/static/", "/uploads/")):
        return False
    if path.startswith("/api/webhook/"):
        return False
    if method == "POST" and "/send" in path and path.startswith("/api/sessions/"):
        return False
    return path == "/" or path.startswith("/api/")
