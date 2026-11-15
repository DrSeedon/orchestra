"""Atomic Antigravity OAuth snapshots; credentials never leave the official CLI."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TOKEN_RELATIVE_PATH = Path(".gemini/antigravity-cli/antigravity-oauth-token")
HARVEST_PENDING_RELATIVE_PATH = Path(".gemini/antigravity-cli/antigravity-oauth-token.harvest-pending")
INSTALLATION_ID_RELATIVE_PATH = Path(".gemini/antigravity-cli/installation_id")
JETSKI_STATE_RELATIVE_PATH = Path(".gemini/antigravity-cli/jetski_state.pbtxt")
SYNC_LOCK_FILENAME = ".oauth-sync.lock"
DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, repr=False)
class AuthSnapshot:
    token: bytes
    generation: str


def derive_auth_generation(token: bytes) -> str:
    """Stable generation across routine hourly ya29 refreshes; changes on account rotation."""
    try:
        parsed = json.loads(token.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        tok = parsed.get("token")
        if isinstance(tok, dict):
            refresh = tok.get("refresh_token")
            if isinstance(refresh, str) and refresh.strip():
                identity = json.dumps(
                    {
                        "auth_method": str(parsed.get("auth_method") or ""),
                        "id_token_email": str(parsed.get("id_token_email") or ""),
                        "refresh_token": refresh.strip(),
                    },
                    sort_keys=True,
                ).encode("utf-8")
                return hashlib.sha256(identity).hexdigest()
    return hashlib.sha256(token).hexdigest()


def _parse_token_identity_and_expiry(token: bytes) -> tuple[str | None, datetime | None]:
    try:
        parsed = json.loads(token.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    tok = parsed.get("token")
    if not isinstance(tok, dict):
        return None, None
    refresh = tok.get("refresh_token")
    identity = (
        f"{parsed.get('auth_method', '')}:{parsed.get('id_token_email', '')}:{refresh.strip()}"
        if isinstance(refresh, str) and refresh.strip()
        else None
    )
    expiry_raw = tok.get("expiry")
    expiry_dt: datetime | None = None
    if isinstance(expiry_raw, str) and expiry_raw.strip():
        norm = re.sub(r"\.(\d{6})\d+", r".\1", expiry_raw.strip().replace("Z", "+00:00"))
        try:
            dt = datetime.fromisoformat(norm)
            if dt.tzinfo is not None:
                expiry_dt = dt
        except ValueError:
            expiry_dt = None
    return identity, expiry_dt


def read_auth_snapshot(auth_home: Path) -> AuthSnapshot:
    token = (Path(auth_home) / TOKEN_RELATIVE_PATH).read_bytes()
    if not token.strip():
        raise ValueError("Antigravity OAuth credential is empty")
    return AuthSnapshot(token, derive_auth_generation(token))


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Antigravity private directory cannot be a symlink")
    path.chmod(0o700)


def atomic_private_write(path: Path, content: bytes) -> None:
    private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".orchestra-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _auth_sync_lock(auth_home: Path, *, timeout: float = DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS):
    auth_home = Path(auth_home)
    private_directory(auth_home)
    lock_path = auth_home / SYNC_LOCK_FILENAME
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    deadline = time.monotonic() + max(0.05, float(timeout))
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out after {timeout:.1f}s waiting for Antigravity OAuth sync lock"
                    ) from exc
                time.sleep(0.01)
        yield
    finally:
        try:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def acquire_turn_slot_fd(auth_home: Path, max_slots: int = 1, *, timeout: float = 600.0) -> int:
    """Acquire a cross-process non-blocking flock slot enforcing ANTIGRAVITY_MAX_CONCURRENT_TURNS."""
    auth_home = Path(auth_home)
    private_directory(auth_home)
    slots = max(1, int(max_slots))
    deadline = time.monotonic() + max(0.1, float(timeout))
    while True:
        for idx in range(slots):
            slot_path = auth_home / f".agy-turn-slot-{idx}.lock"
            fd = os.open(slot_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                os.close(fd)
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out after {timeout:.1f}s waiting for Antigravity execution slot (max={slots})"
            )
        time.sleep(0.02)


def release_turn_slot_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _sync_machine_identity_unlocked(auth_home: Path, session_home: Path) -> None:
    """Ensure canonical auth_home and every session_home share one installation_id & installation_uuid."""
    auth_inst = auth_home / INSTALLATION_ID_RELATIVE_PATH
    inst_bytes = auth_inst.read_bytes().strip() if auth_inst.is_file() else b""
    if not inst_bytes:
        inst_bytes = str(uuid.uuid4()).encode("ascii")
        atomic_private_write(auth_inst, inst_bytes)
    inst_str = inst_bytes.decode("ascii", errors="replace").strip() or str(uuid.uuid4())

    sess_inst = session_home / INSTALLATION_ID_RELATIVE_PATH
    if not sess_inst.is_file() or sess_inst.read_bytes().strip() != inst_bytes:
        atomic_private_write(sess_inst, inst_bytes)

    auth_jetski = auth_home / JETSKI_STATE_RELATIVE_PATH
    if auth_jetski.is_file():
        auth_state_text = auth_jetski.read_text(encoding="utf-8", errors="replace")
    else:
        auth_state_text = ""

    m = re.search(r'installation_uuid:\s*"([^"]+)"', auth_state_text)
    if m:
        canon_uuid = m.group(1)
    else:
        canon_uuid = inst_str
        prefix = auth_state_text.rstrip()
        auth_state_text = (f"{prefix}\n" if prefix else "") + f'installation_uuid: "{canon_uuid}"\n'
        atomic_private_write(auth_jetski, auth_state_text.encode("utf-8"))

    sess_jetski = session_home / JETSKI_STATE_RELATIVE_PATH
    if not sess_jetski.is_file():
        atomic_private_write(sess_jetski, auth_state_text.encode("utf-8"))
    else:
        sess_text = sess_jetski.read_text(encoding="utf-8", errors="replace")
        if re.search(r'installation_uuid:\s*"([^"]+)"', sess_text):
            updated = re.sub(
                r'installation_uuid:\s*"[^"]+"',
                f'installation_uuid: "{canon_uuid}"',
                sess_text,
            )
        else:
            updated = sess_text.rstrip() + f'\ninstallation_uuid: "{canon_uuid}"\n'
        if updated != sess_text:
            atomic_private_write(sess_jetski, updated.encode("utf-8"))


def _promote_fresher_session_token_unlocked(auth_home: Path, session_home: Path) -> bool:
    """If session_home (or its .harvest-pending backup) holds a fresher ya29, write back to auth_home."""
    auth_token_path = auth_home / TOKEN_RELATIVE_PATH
    if not auth_token_path.is_file():
        return False
    sess_token_path = session_home / TOKEN_RELATIVE_PATH
    pending_path = session_home / HARVEST_PENDING_RELATIVE_PATH

    candidates: list[Path] = []
    if sess_token_path.is_file():
        candidates.append(sess_token_path)
    if pending_path.is_file():
        candidates.append(pending_path)
    if not candidates:
        return False

    auth_bytes = auth_token_path.read_bytes()
    auth_id, auth_exp = _parse_token_identity_and_expiry(auth_bytes)
    if auth_id is None:
        return False

    best_bytes: bytes | None = None
    best_exp = auth_exp
    for cand in candidates:
        try:
            raw = cand.read_bytes()
        except OSError:
            continue
        if not raw.strip() or raw == auth_bytes:
            continue
        cid, cexp = _parse_token_identity_and_expiry(raw)
        if cid == auth_id and cexp is not None and (best_exp is None or cexp > best_exp):
            best_bytes = raw
            best_exp = cexp

    if best_bytes is None:
        if pending_path.is_file():
            pending_path.unlink(missing_ok=True)
        return False

    try:
        atomic_private_write(auth_token_path, best_bytes)
    except BaseException:
        # Preserve refreshed token privately so session token cleanup never loses it!
        try:
            atomic_private_write(pending_path, best_bytes)
        except OSError:
            pass
        raise

    pending_path.unlink(missing_ok=True)
    return True


def sync_antigravity_home(auth_home: Path, session_home: Path) -> None:
    """Synchronize single installation_id/jetski_state and promote any fresher ya29 under flock."""
    auth_home = Path(auth_home)
    session_home = Path(session_home)
    if not auth_home.exists():
        return
    private_directory(session_home)
    with _auth_sync_lock(auth_home):
        _sync_machine_identity_unlocked(auth_home, session_home)
        _promote_fresher_session_token_unlocked(auth_home, session_home)


def harvest_refreshed_session_token(auth_home: Path, session_home: Path) -> bool:
    """Harvest a CLI-refreshed ya29 token from session_home back into canonical auth_home."""
    auth_home = Path(auth_home)
    session_home = Path(session_home)
    if not (auth_home / TOKEN_RELATIVE_PATH).is_file():
        return False
    if not (session_home / TOKEN_RELATIVE_PATH).is_file() and not (
        session_home / HARVEST_PENDING_RELATIVE_PATH
    ).is_file():
        return False
    with _auth_sync_lock(auth_home):
        return _promote_fresher_session_token_unlocked(auth_home, session_home)


def promote_staged_token(auth_home: Path, staged_token: Path) -> str:
    """One replacement is the transaction: generation is derived, never stored apart."""
    snapshot = staged_token.read_bytes()
    if not snapshot.strip():
        raise ValueError("Antigravity staged credential is empty")
    auth_home = Path(auth_home)
    with _auth_sync_lock(auth_home):
        target = auth_home / TOKEN_RELATIVE_PATH
        private_directory(target.parent)
        staged_token.chmod(0o600)
        with staged_token.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(staged_token, target)
        directory_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return derive_auth_generation(snapshot)


def ensure_credits_disabled(home: Path) -> None:
    home = Path(home)
    settings_path = home / ".gemini/antigravity-cli/settings.json"
    settings_data = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text())
            if isinstance(loaded, dict):
                settings_data = loaded
        except (OSError, ValueError):
            pass
    settings_data["useG1Credits"] = False
    settings_data["telemetryEnabled"] = False
    atomic_private_write(settings_path, json.dumps(settings_data, indent=2).encode())

    cfg_path = home / ".gemini/config/config.json"
    cfg_data = {}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text())
            if isinstance(loaded, dict):
                cfg_data = loaded
        except (OSError, ValueError):
            pass
    user_settings = cfg_data.get("userSettings")
    if not isinstance(user_settings, dict):
        user_settings = {}
    user_settings["useAiCredits"] = False
    user_settings["telemetryEnabled"] = False
    user_settings["userDataCollectionForceDisabled"] = True
    user_settings["marketingEmailsEnabled"] = False
    cfg_data["userSettings"] = user_settings
    atomic_private_write(cfg_path, json.dumps(cfg_data, indent=2).encode())


def main() -> int:
    """Operator-only login, staging validation and atomic account promotion."""
    import argparse
    import asyncio
    import subprocess
    import sys
    from app import backend_antigravity as backend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agy-bin", default=backend.ANTIGRAVITY_BIN)
    parser.add_argument("--auth-home", type=Path, default=backend.ANTIGRAVITY_AUTH_HOME)
    parser.add_argument("--model", default="gemini-3.6-flash-low")
    args = parser.parse_args()
    backend.ANTIGRAVITY_BIN = args.agy_bin
    backend.ANTIGRAVITY_AUTH_HOME = args.auth_home
    args.auth_home.parent.mkdir(parents=True, exist_ok=True)

    async def validate(home):
        version = await backend._cli("--version", home=home)
        if not isinstance(version, str) or not backend.supported_version(version):
            raise RuntimeError("Antigravity requires CLI >= 1.1.12")
        models = await backend._cli("--output-format", "json", "models", home=home)
        if args.model.removeprefix("antigravity/") not in backend.catalog_models(models):
            raise RuntimeError("Requested model missing from Antigravity live catalog")
        quota = backend.normalize_antigravity_quota(await backend._cli(
            "--output-format", "json", "-p", "/quota", home=home))
        if not all(quota.values()):
            raise RuntimeError("Antigravity account/quota validation failed")
        read_auth_snapshot(home)

    try:
        with tempfile.TemporaryDirectory(prefix=".antigravity-login.", dir=args.auth_home.parent) as temporary:
            home = Path(temporary)
            ensure_credits_disabled(home)
            subprocess.run([args.agy_bin], env=backend.cli_environment(home), check=True)
            ensure_credits_disabled(home)
            asyncio.run(validate(home))
            generation = promote_staged_token(args.auth_home, home / TOKEN_RELATIVE_PATH)
            ensure_credits_disabled(args.auth_home)
        print(f"Antigravity account validated: gemini-weekly, 3p-weekly; generation {generation}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, TimeoutError):
        print("Antigravity login failed; previous canonical credential preserved", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
