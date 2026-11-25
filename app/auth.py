"""Dashboard authentication — random DB-backed revocable session tokens."""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

DASHBOARD_SESSION_TTL_SECONDS = 30 * 24 * 3600


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


def _cred_fingerprint(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}\x00{password}".encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(username: str) -> str:
    """Create a cryptographically random dashboard session token persisted in SQLite."""
    from app import db

    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + DASHBOARD_SESSION_TTL_SECONDS
    user = os.environ.get("DASHBOARD_USER", "")
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    fingerprint = _cred_fingerprint(user, password)
    with db._conn() as conn:
        db._ensure_dashboard_sessions_schema(conn)
        conn.execute("DELETE FROM dashboard_sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            """INSERT INTO dashboard_sessions (
                   token_hash, username, cred_fingerprint, created_at, expires_at, revoked_at
               ) VALUES (?, ?, ?, ?, ?, NULL)""",
            (_token_hash(token), username, fingerprint, now, expires_at),
        )
    return token


def revoke_session(token: str) -> None:
    """Revoke a dashboard session token immediately in SQLite and purge expired rows."""
    if not token:
        return
    from app import db

    now = time.time()
    with db._conn() as conn:
        db._ensure_dashboard_sessions_schema(conn)
        conn.execute(
            "UPDATE dashboard_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (now, _token_hash(token)),
        )
        conn.execute("DELETE FROM dashboard_sessions WHERE expires_at <= ?", (now,))


def create_csrf_token(username: str) -> str:
    secret = os.environ.get("DASHBOARD_PASSWORD", "")
    return hmac.new(
        secret.encode(), f"csrf:{username}".encode(), hashlib.sha256
    ).hexdigest()


def validate_session(token: str) -> bool:
    if not token:
        return False
    user = os.environ.get("DASHBOARD_USER", "")
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not user or not password:
        return False
    from app import db

    now = time.time()
    expected_fp = _cred_fingerprint(user, password)
    with db._conn() as conn:
        db._ensure_dashboard_sessions_schema(conn)
        row = conn.execute(
            "SELECT cred_fingerprint, expires_at, revoked_at FROM dashboard_sessions WHERE token_hash = ?",
            (_token_hash(token),),
        ).fetchone()
    if row is None or row["revoked_at"] is not None:
        return False
    if float(row["expires_at"]) <= now:
        return False
    return hmac.compare_digest(row["cred_fingerprint"], expected_fp)


def require_operator_session(request: Request) -> None:
    """Require a real dashboard login for quota/control-plane mutations."""
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail="operator mutation requires dashboard authentication",
        )
    if not validate_session(request.cookies.get("session", "")):
        raise HTTPException(status_code=403, detail="operator session required")


def require_operator_csrf(request: Request) -> None:
    require_operator_session(request)
    username = os.environ.get("DASHBOARD_USER", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = create_csrf_token(username)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="operator CSRF token required")


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
    if path.startswith("/charts/"):
        return True
    from app.artifacts import is_public_artifact_request
    if is_public_artifact_request(path, method):
        return False
    # Malformed slash-prefixed API paths are protected too; only the exact artifact shapes above
    # may bypass auth, and a proxy must not turn a doubled slash into an anonymous API request.
    return (
        path == "/"
        or path.startswith("/api/")
        or path.startswith("//api/")
        or path in {"/openapi.json", "/docs", "/redoc"}
    )
