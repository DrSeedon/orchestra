"""Private Gemini Web credentials; operator imports JSON through stdin only."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

from app.antigravity_auth import atomic_private_write, private_directory

COOKIE_NAMES = ("__Secure-1PSID", "__Secure-1PSIDTS", "SID", "HSID", "SSID",
                "APISID", "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID",
                "__Secure-3PSID", "__Secure-3PSIDTS", "SIDCC", "__Secure-1PSIDCC",
                "__Secure-3PSIDCC", "LSID", "__Host-1PLSID", "__Host-3PLSID")
MODELS = {
    "gemini-argon": "4 Argon", "gemini-pro": "3.1 Pro",
    "gemini-flash": "3.8 Flash", "gemini-flash-lite": "3.5 Flash-Lite",
}
# Disabled per owner request (theiskraschool commented out / excluded from active pool):
# "theiskraschool@gmail.com"
DISABLED_ACCOUNT_EMAILS = frozenset({
    "theiskraschool@gmail.com",
})
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
    if "accounts" in payload:
        accounts = payload["accounts"]
        if (not isinstance(accounts, list) or not accounts
                or "cookies" in payload or "expected_email" in payload):
            raise ValueError("Gemini Web requires a nonempty account pool")
        clean = []
        seen = set()
        for account in accounts:
            if not isinstance(account, dict) or "accounts" in account:
                raise ValueError("Gemini Web pool entries must be individual accounts")
            account = validate_auth(account)
            if account["expected_email"] in seen:
                raise ValueError("Gemini Web pool requires unique account emails")
            seen.add(account["expected_email"])
            clean.append(account)
        return {"accounts": clean}
    cookies = payload.get("cookies")
    email = payload.get("expected_email")
    if (not isinstance(cookies, dict) or not set(cookies) <= set(COOKIE_NAMES)
            or not cookies.get("__Secure-1PSID")
            or any(not isinstance(cookies[name], str) or not cookies[name].strip()
                   for name in cookies)):
        raise ValueError("Gemini Web requires valid Google session cookies")
    if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", email):
        raise ValueError("Gemini Web requires an expected account email")
    clean = {"cookies": dict(cookies), "expected_email": email.lower()}
    if "disabled" in payload:
        if type(payload["disabled"]) is not bool:
            raise ValueError("Gemini Web account disabled flag must be a boolean")
        clean["disabled"] = payload["disabled"]
    if "authuser_index" in payload:
        index = payload["authuser_index"]
        if type(index) is not int or index < 0:
            raise ValueError("Gemini Web account index must be a nonnegative integer")
        clean["authuser_index"] = index
    return clean


def write_auth(payload: object, path: Path | None = None) -> None:
    clean = validate_auth(payload)
    path = path or auth_path()
    private_directory(path.parent)
    fd = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        atomic_private_write(path, json.dumps(clean).encode())
    finally:
        os.close(fd)


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


def read_accounts(path: Path | None = None) -> list[dict]:
    payload = read_auth(path)
    accounts = payload["accounts"] if "accounts" in payload else [payload]
    return [account for account in accounts
            if account.get("expected_email", "").lower() not in DISABLED_ACCOUNT_EMAILS
            and account.get("disabled") is not True]


def persist_cookies(previous: dict, updated: dict, path: Path | None = None) -> bool:
    """CAS update all slots sharing this Google login; never overwrite a newer import.

    Lock the private directory inode so atomic auth.json replacement cannot release
    the lock, and no lock/cache file containing credentials is needed.
    """
    if not updated:
        return False
    validate_auth({**previous, "cookies": {**previous["cookies"], **updated}})
    path = path or auth_path()
    fd = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        payload = read_auth(path)
        accounts = payload.get("accounts", [payload])
        if not any(account["cookies"] == previous["cookies"] for account in accounts):
            return False
        changed = False
        for account in accounts:
            if (account["cookies"] == previous["cookies"]
                    or account["cookies"].get("__Secure-1PSID") == previous["cookies"].get("__Secure-1PSID")):
                if all(account["cookies"].get(name) == value for name, value in updated.items()):
                    continue
                account["cookies"].update(updated)
                changed = True
        if changed:
            atomic_private_write(path, json.dumps(payload).encode())
        return changed
    finally:
        os.close(fd)


def account_label(account: dict, *, short: bool = False) -> str:
    local, domain = account["expected_email"].rsplit("@", 1)
    masked = local[:3] + "…" + (local[-3:] if len(local) > 3 else "")
    return f"u/{account.get('authuser_index', 0)} {masked}" if short else masked + "@" + domain


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


def redact_secrets(text: str, auth_or_cookies: dict | list | None = None) -> str:
    def values(payload):
        if isinstance(payload, list):
            for account in payload:
                yield from values(account)
        elif isinstance(payload, dict):
            if "accounts" in payload:
                yield from values(payload["accounts"])
            elif "cookies" in payload:
                yield from values(payload["cookies"])
            else:
                for name in COOKIE_NAMES:
                    value = payload.get(name)
                    if isinstance(value, str) and value:
                        yield value

    for value in sorted(set(values(auth_or_cookies)), key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    return re.sub(
        r'((?:' + '|'.join(map(re.escape, COOKIE_NAMES)) + r')[\s\"\x27]*[:=][\s\"\x27]*)[^\s\"\x27;,}]+',
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
