"""Atomic Antigravity OAuth snapshots; credentials never leave the official CLI."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

TOKEN_RELATIVE_PATH = Path(".gemini/antigravity-cli/antigravity-oauth-token")


@dataclass(frozen=True, repr=False)
class AuthSnapshot:
    token: bytes
    generation: str


def read_auth_snapshot(auth_home: Path) -> AuthSnapshot:
    token = (Path(auth_home) / TOKEN_RELATIVE_PATH).read_bytes()
    if not token.strip():
        raise ValueError("Antigravity OAuth credential is empty")
    return AuthSnapshot(token, hashlib.sha256(token).hexdigest())


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
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def promote_staged_token(auth_home: Path, staged_token: Path) -> str:
    """One replacement is the transaction: generation is derived, never stored apart."""
    snapshot = staged_token.read_bytes()
    if not snapshot.strip():
        raise ValueError("Antigravity staged credential is empty")
    private_directory(Path(auth_home))
    target = Path(auth_home) / TOKEN_RELATIVE_PATH
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
    return hashlib.sha256(snapshot).hexdigest()



def ensure_credits_disabled(home: Path) -> None:
    import json
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
            # The official interactive OAuth command inherits the operator's TTY.
            subprocess.run([args.agy_bin], env=backend.cli_environment(home), check=True)
            ensure_credits_disabled(home)
            asyncio.run(validate(home))
            generation = promote_staged_token(args.auth_home, home / TOKEN_RELATIVE_PATH)
            ensure_credits_disabled(args.auth_home)
        print(f"Antigravity account validated: gemini-weekly, 3p-weekly; generation {generation}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, TimeoutError):
        # Vendor output may contain credentials; print only our own failure message.
        print("Antigravity login failed; previous canonical credential preserved", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
