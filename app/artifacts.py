"""Private immutable artifact snapshots and capability grants.

The public link surface deliberately lives here rather than in the legacy file routes.  A row
contains only a verifier and a server-generated private filename; source paths and bearer tokens
never enter durable state.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.db import _conn

MAX_BYTES = 10 * 1024 * 1024
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_LOCATOR_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class ArtifactConfig:
    enabled: bool
    base_url: str
    secret: bytes
    default_ttl: int
    max_ttl: int
    max_bytes: int


def _decode_secret(raw: str) -> bytes | None:
    if not raw or "=" in raw or not _TOKEN_RE.fullmatch(raw):
        return None
    try:
        value = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError):
        return None
    return value if len(value) >= 32 else None


def _origin(raw: str) -> str | None:
    try:
        parsed = urlsplit(raw)
        if parsed.scheme != "https" or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        if parsed.path not in ("", "/"):
            return None
        # Accessing port rejects malformed/non-numeric ports.
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"https://{host}{f':{port}' if port else ''}"


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if minimum <= value <= maximum else None


def load_artifact_config() -> ArtifactConfig:
    default_ttl = _int_env("ARTIFACT_DEFAULT_TTL_SECONDS", 86400, 1, 604800)
    max_ttl = _int_env("ARTIFACT_MAX_TTL_SECONDS", 604800, 1, 604800)
    max_bytes = _int_env("ARTIFACT_MAX_BYTES", MAX_BYTES, 1, MAX_BYTES)
    secret = _decode_secret(os.environ.get("ARTIFACT_LINK_SECRET", ""))
    base_url = _origin(os.environ.get("PUBLIC_BASE_URL", ""))
    enabled = (
        os.environ.get("ARTIFACT_PUBLIC_LINKS_ENABLED") == "1"
        and base_url is not None
        and secret is not None
        and default_ttl is not None
        and max_ttl is not None
        and max_bytes is not None
        and default_ttl <= max_ttl
    )
    return ArtifactConfig(
        enabled=enabled,
        base_url=base_url or "",
        secret=secret or b"",
        default_ttl=default_ttl or 86400,
        max_ttl=max_ttl or 604800,
        max_bytes=max_bytes or MAX_BYTES,
    )


def is_public_artifact_request(path: str, method: str) -> bool:
    """Return whether auth may be bypassed for one exact public artifact operation."""
    cfg = load_artifact_config()
    if not cfg.enabled:
        return False
    method = method.upper()
    if not isinstance(path, str):
        return False
    match = re.fullmatch(r"/api/artifacts/open/([A-Za-z0-9_-]{22})(/redeem|/content)?", path)
    if not match:
        return False
    suffix = match.group(2) or ""
    return (suffix == "" and method in {"GET", "HEAD"}) or (
        suffix == "/redeem" and method == "POST"
    ) or (suffix == "/content" and method == "GET")


def _state_root() -> Path:
    state = os.environ.get("STATE_DIRECTORY", "").strip()
    if state and os.pathsep not in state:
        return Path(state).expanduser().absolute()
    xdg = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg and os.pathsep not in xdg:
        return (Path(xdg).expanduser() / "orchestra").absolute()
    return (Path.home() / ".local" / "state" / "orchestra").absolute()


def private_store() -> Path:
    root = _state_root() / "artifacts"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def _now(now: int | float | None) -> int:
    return int(now if now is not None else __import__("time").time())


def _safe_name(value: str) -> bool:
    return bool(_LOCATOR_RE.fullmatch(value))


def _read_fd(fd: int, cap: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(1024 * 1024, cap + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            raise ValueError("artifact exceeds configured size limit")
    return b"".join(chunks)


def _authorized_source(source_path: str, allowed_roots: tuple[str, ...]) -> tuple[int, str]:
    source = Path(source_path)
    if not source.is_absolute():
        raise ValueError("source path must be absolute")
    source = Path(os.path.abspath(source))
    for root_raw in allowed_roots:
        root = Path(root_raw)
        if not root.is_absolute():
            continue
        root = Path(os.path.abspath(root))
        try:
            relative = source.relative_to(root)
        except ValueError:
            continue
        if any(part in ("", ".", "..") for part in relative.parts):
            continue
        if not root.is_dir():
            continue
        current = root
        try:
            # Open every directory component beneath the registered root.  Checking Path objects
            # first is useful for diagnostics, but cannot close the rename-to-symlink window;
            # dirfd traversal with O_NOFOLLOW makes the descriptor identity authoritative.
            root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
            parent_fd = root_fd
            try:
                for part in relative.parts[:-1]:
                    child_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    if parent_fd != root_fd:
                        os.close(parent_fd)
                    parent_fd = child_fd
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
                if parent_fd != root_fd:
                    os.close(root_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise ValueError("source is not a regular file")
            return fd, source.name
        except OSError:
            raise
    raise ValueError("source path is outside registered roots")


def _write_private(locator: str, body: bytes) -> Path:
    store = private_store()
    target = store / f"{locator}.html"
    temp = store / f".{locator}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(temp), flags, 0o600)
    try:
        offset = 0
        while offset < len(body):
            offset += os.write(fd, body[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, target)
    target.chmod(0o600)
    dir_fd = os.open(str(store), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return target


def _capability_verifier(capability: str, secret: bytes) -> bytes:
    return hmac.new(secret, b"artifact-cap-v1\0" + capability.encode("ascii"), hashlib.sha256).digest()


def publish_snapshot(
    *, source_path: str, allowed_roots: tuple[str, ...], publisher_session_id: str,
    publisher_name: str, scope: str, ttl_seconds: int, now: int | float | None = None,
) -> dict:
    cfg = load_artifact_config()
    if not cfg.enabled:
        raise ValueError("artifact links are disabled")
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid artifact TTL") from exc
    if not 1 <= ttl <= cfg.max_ttl:
        raise ValueError("artifact TTL is outside configured limits")
    timestamp = _now(now)
    fd, display_name = _authorized_source(source_path, tuple(allowed_roots))
    body: bytes
    try:
        body = _read_fd(fd, cfg.max_bytes)
    finally:
        os.close(fd)
    if not body:
        raise ValueError("artifact is empty")
    locator = secrets.token_urlsafe(16)
    capability = secrets.token_urlsafe(32)
    stored = _write_private(locator, body)
    try:
        with _conn() as conn:
            conn.execute(
                """INSERT INTO artifacts (
                   id, capability_verifier, stored_name, content_sha256, display_name,
                   publisher_session_id, publisher_name, scope, size_bytes, created_at,
                   expires_at, state, activated_at, revoked_at, last_opened_at, open_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, 0)""",
                (
                    locator, _capability_verifier(capability, cfg.secret), stored.name,
                    hashlib.sha256(body).digest(), display_name, publisher_session_id,
                    publisher_name, scope, len(body), timestamp, timestamp + ttl,
                ),
            )
    except Exception:
        stored.unlink(missing_ok=True)
        raise
    return {
        "id": locator,
        "capability": capability,
        "content_sha256": hashlib.sha256(body).digest(),
        "size_bytes": len(body),
        "expires_at": timestamp + ttl,
        "display_name": display_name,
    }


def activate_artifact(locator: str, now: int | float | None = None) -> bool:
    timestamp = _now(now)
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE artifacts SET state='active', activated_at=? "
            "WHERE id=? AND state='pending' AND expires_at>?",
            (timestamp, locator, timestamp),
        )
        return cursor.rowcount == 1


def revoke_artifact(locator: str, now: int | float | None = None) -> bool:
    timestamp = _now(now)
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE artifacts SET state='revoked', revoked_at=? "
            "WHERE id=? AND state IN ('pending','active')",
            (timestamp, locator),
        )
        return cursor.rowcount == 1


def discard_pending_artifact(locator: str) -> bool:
    """Remove an unpublished copy and durably mark its row revoked after delivery ambiguity."""
    if not _safe_name(locator):
        return False
    with _conn() as conn:
        row = conn.execute(
            "SELECT stored_name FROM artifacts WHERE id=? AND state='pending'", (locator,)
        ).fetchone()
        if row is None:
            return False
        name = str(row["stored_name"])
        if re.fullmatch(r"[A-Za-z0-9_-]{22}\.html", name):
            (private_store() / name).unlink(missing_ok=True)
        conn.execute(
            "UPDATE artifacts SET state='revoked', revoked_at=strftime('%s','now') "
            "WHERE id=? AND state='pending'",
            (locator,),
        )
        return True


def discard_artifact(locator: str) -> bool:
    """Delete the private copy and durably revoke a pending or active artifact."""
    if not _safe_name(locator):
        return False
    with _conn() as conn:
        row = conn.execute(
            "SELECT stored_name, state FROM artifacts WHERE id=? AND state IN ('pending','active')",
            (locator,),
        ).fetchone()
        if row is None:
            return False
        name = str(row["stored_name"])
        if re.fullmatch(r"[A-Za-z0-9_-]{22}\.html", name):
            (private_store() / name).unlink(missing_ok=True)
        conn.execute(
            "UPDATE artifacts SET state='revoked', revoked_at=strftime('%s','now') WHERE id=?",
            (locator,),
        )
        return True


def _artifact_row(locator: str):
    if not _safe_name(locator):
        return None
    with _conn() as conn:
        return conn.execute("SELECT * FROM artifacts WHERE id=?", (locator,)).fetchone()


def open_artifact_buffer(locator: str, now: int | float | None = None) -> bytes:
    timestamp = _now(now)
    row = _artifact_row(locator)
    if row is None or row["state"] != "active" or int(row["expires_at"]) <= timestamp:
        raise FileNotFoundError("artifact not found")
    stored_name = str(row["stored_name"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{22}\.html", stored_name):
        raise ValueError("invalid artifact storage name")
    target = private_store() / stored_name
    # O_RDWR keeps the descriptor suitable for an integrity probe that mutates the opened inode;
    # serving still performs no writes and the private file is mode 0600.
    fd = os.open(str(target), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("artifact is not a regular file")
        body = _read_fd(fd, min(MAX_BYTES, int(row["size_bytes"])))
    finally:
        os.close(fd)
    if len(body) != int(row["size_bytes"]) or hashlib.sha256(body).digest() != bytes(row["content_sha256"]):
        raise ValueError("artifact integrity check failed")
    try:
        with _conn() as conn:
            conn.execute(
                "UPDATE artifacts SET last_opened_at=?, open_count=open_count+1 WHERE id=? AND state='active'",
                (timestamp, locator),
            )
    except Exception:
        pass
    return body


def grant_value(locator: str, expires_at: int, secret: bytes) -> str:
    payload = f"v1.{locator}.{int(expires_at)}"
    signature = hmac.new(secret, b"artifact-grant-v1\0" + payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def verify_grant(locator: str, value: str, now: int | float | None = None) -> bool:
    cfg = load_artifact_config()
    if not cfg.enabled or not _safe_name(locator):
        return False
    parts = (value or "").split(".")
    if len(parts) != 4 or parts[0] != "v1" or parts[1] != locator or not parts[2].isdigit():
        return False
    try:
        expires = int(parts[2])
        supplied = base64.urlsafe_b64decode(parts[3] + "=" * (-len(parts[3]) % 4))
    except (ValueError, TypeError):
        return False
    expected = hmac.new(
        cfg.secret, f"artifact-grant-v1\0v1.{locator}.{expires}".encode(), hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied, expected):
        return False
    timestamp = _now(now)
    row = _artifact_row(locator)
    return bool(row and row["state"] == "active" and timestamp < expires and timestamp < int(row["expires_at"]))


def public_url(locator: str, capability: str) -> str:
    cfg = load_artifact_config()
    return f"{cfg.base_url}/api/artifacts/open/{locator}#{capability}"


def cleanup_expired(now: int | float | None = None) -> int:
    """Delete only files named by expired registry rows; disabled mode is safe."""
    timestamp = _now(now)
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, stored_name FROM artifacts WHERE expires_at <= ?", (timestamp,)
        ).fetchall()
        if not rows:
            return 0
        for row in rows:
            name = str(row["stored_name"])
            if re.fullmatch(r"[A-Za-z0-9_-]{22}\.html", name):
                (private_store() / name).unlink(missing_ok=True)
            conn.execute("DELETE FROM artifacts WHERE id=?", (row["id"],))
    return len(rows)
