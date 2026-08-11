"""Dashboard authentication — deterministic HMAC tokens from .env credentials."""

import hashlib
import hmac
import os

from fastapi import HTTPException, Request


def is_auth_enabled() -> bool:
    return bool(os.environ.get("DASHBOARD_USER") or os.environ.get("DASHBOARD_PASSWORD"))


def is_owner_mode() -> bool:
    """Машина наша → дашборд показывает НАШИ квоты, прокси и профили Claude.

    Это НЕ про логин: `is_auth_enabled()` решает только «спрашивать ли пароль».
    Дефолт = старое поведение: без логина машина считается нашей (дев-ноут),
    с логином — клиентской. `OWNER_MODE` перебивает обе стороны: на нашем VPS
    логин включён, но данные наши → `OWNER_MODE=1`.
    """
    explicit = os.environ.get("OWNER_MODE", "").strip().lower()
    if explicit:
        return explicit in ("1", "true", "yes")
    return not is_auth_enabled()


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
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not user or not password:
        return False
    return hmac.compare_digest(token, _make_token(user))


def require_operator_session(request: Request) -> None:
    """Require a real dashboard login for quota/control-plane mutations."""
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail="operator mutation requires dashboard authentication",
        )
    if not validate_session(request.cookies.get("session", "")):
        raise HTTPException(status_code=403, detail="operator session required")


def check_internal_token(auth_header: str) -> bool:
    token = os.environ.get("INTERNAL_TOKEN", "")
    if not token:
        return False
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
    if path.startswith("/uploads/"):
        return True
    return path == "/" or path.startswith("/api/")
