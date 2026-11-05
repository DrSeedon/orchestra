"""Private Gemini Web credentials; operator imports JSON through stdin only."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

from app.antigravity_auth import atomic_private_write

COOKIE_NAMES = ("__Secure-1PSID", "__Secure-1PSIDTS")
MODELS = {
    "gemini-argon": "4 Argon", "gemini-pro": "3.1 Pro",
    "gemini-flash": "3.8 Flash", "gemini-flash-lite": "3.5 Flash-Lite",
}
ROOT = Path(__file__).resolve().parent.parent


def auth_path() -> Path:
    override = os.environ.get("GEMINI_WEB_AUTH_FILE")
    if override:
        return Path(override).expanduser()
    home = os.environ.get("ORCHESTRA_HOME")
    if home:
        return Path(home).expanduser() / "gemini-web/auth.json"
    database = os.environ.get("ORCHESTRA_DB_PATH", "data/orchestra.db")
    return (ROOT / database).parent / "gemini-web/auth.json"


def validate_auth(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Gemini Web authorization must be an object")
    cookies = payload.get("cookies")
    email = payload.get("expected_email")
    if (not isinstance(cookies, dict) or set(cookies) != set(COOKIE_NAMES)
            or any(not isinstance(cookies[name], str) or not cookies[name].strip()
                   for name in COOKIE_NAMES)):
        raise ValueError("Gemini Web requires both authentication cookies")
    if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", email):
        raise ValueError("Gemini Web requires an expected account email")
    return {"cookies": dict(cookies), "expected_email": email.lower()}


def write_auth(payload: object, path: Path | None = None) -> None:
    clean = validate_auth(payload)
    atomic_private_write(path or auth_path(), json.dumps(clean).encode())


def read_auth(path: Path | None = None) -> dict:
    path = path or auth_path()
    # Fail closed on shared files or symlinks, including a replaced private directory.
    for target, mode in ((path.parent, 0o700), (path, 0o600)):
        info = target.lstat()
        if (stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) != mode
                or info.st_uid != os.getuid()):
            raise ValueError("Gemini Web authorization requires private owner-only paths")
    if not path.is_file():
        raise ValueError("Gemini Web authorization must be a regular file")
    try:
        return validate_auth(json.loads(path.read_bytes()))
    except (ValueError, TypeError):
        raise ValueError("Gemini Web authorization is invalid") from None


def helper_python() -> str | None:
    configured = os.environ.get("GEMINI_WEB_PYTHON")
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    if importlib.util.find_spec("gemini_webapi") is not None:
        return sys.executable
    for candidate in (
        ROOT / "data/gemini-web-pilot/.venv/bin/python",
        Path.home() / ".local/share/orchestra-gemini-web-pilot/.venv/bin/python",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def gemini_web_readiness() -> dict:
    try:
        read_auth()
    except (OSError, ValueError):
        return {"ready": False, "reason": "Gemini Web private authorization missing or invalid"}
    if helper_python() is None:
        return {"ready": False, "reason": "Gemini Web helper Python unavailable (GEMINI_WEB_PYTHON)"}
    return {"ready": True, "reason": "Local credentials and helper available; identity checked per request"}


def redact_secrets(text: str, cookies: dict | None = None) -> str:
    for value in sorted((cookies or {}).values(), key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    return re.sub(
        r'(__Secure-1PSID(?:TS)?[\s\"\x27]*[:=][\s\"\x27]*)[^\s\"\x27;,}]+',
        r'\1[REDACTED]', text,
    )


def main() -> int:
    try:
        write_auth(json.load(sys.stdin))
    except Exception:
        print("Gemini Web authorization import failed", file=sys.stderr)
        return 1
    print("Gemini Web authorization installed (directory 0700, file 0600)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
