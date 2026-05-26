"""Dashboard authentication — deterministic HMAC tokens from .env credentials."""

import hashlib
import hmac
import os


def is_auth_enabled() -> bool:
    return bool(os.environ.get("DASHBOARD_USER") or os.environ.get("DASHBOARD_PASSWORD"))


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("DASHBOARD_USER", "")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    return (
        hmac.compare_digest(username.encode(), expected_user.encode())
        and hmac.compare_digest(password.encode(), expected_pass.encode())
    )


def _make_token(username: str) -> str:
    secret = os.environ.get("DASHBOARD_PASSWORD", "")
    return hmac.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()


def create_session(username: str) -> str:
    return _make_token(username)


def validate_session(token: str) -> bool:
    if not token:
        return False
    user = os.environ.get("DASHBOARD_USER", "")
    if not user:
        return False
    return hmac.compare_digest(token, _make_token(user))


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
    if path.startswith("/static/"):
        return False
    if path.startswith("/api/webhook/"):
        return False
    return path == "/" or path.startswith("/api/")
