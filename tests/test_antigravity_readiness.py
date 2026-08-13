"""Frozen RED for #249 T3: account rotation and #247 runtime readiness adapter."""

import asyncio
import hashlib
import importlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
LOGIN_SCRIPT = ROOT / "scripts/antigravity-login.sh"
RUNBOOK = ROOT / "docs/antigravity-runtime.md"


def _backend_module():
    try:
        module = importlib.import_module("app.backend_antigravity")
    except ModuleNotFoundError:
        module = None
    assert module is not None, "Antigravity backend module is missing"
    return module


def _write_fake_agy(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
mode = os.environ.get("FAKE_AGY_MODE", "success")
home = Path(os.environ["HOME"])
state = home / ".gemini/antigravity-cli"
state.mkdir(parents=True, exist_ok=True)
token_path = state / "antigravity-oauth-token"
if mode != "missing-token":
    token_path.write_text(os.environ.get("FAKE_AGY_TOKEN", "new-token-not-real"))
    token_path.chmod(0o600)

if not args:
    print("OAuth login completed")
    raise SystemExit(0)

if args == ["--version"]:
    print("1.1.11" if mode == "wrong-version" else "1.1.12")
    raise SystemExit(0)

if args[-1:] == ["models"]:
    models = [{"id": "gemini-3.6-flash-low", "label": "Gemini 3.6 Flash (Low)"}]
    if mode == "missing-model":
        models = [{"id": "gemini-3.5-flash-low", "label": "other"}]
    print(json.dumps({
        "conversation_id": "",
        "status": "SUCCESS",
        "response": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "command": {"name": "models", "data": {"models": models}},
    }))
    raise SystemExit(0)

if "/quota" in args:
    if mode in {"quota-error", "eligibility-error", "oauth-prompt"}:
        print(json.dumps({
            "conversation_id": "",
            "status": "ERROR",
            "response": "",
            "error": (
                "Eligibility check failed: not currently available in your location"
                if mode == "eligibility-error"
                else (
                    "Enter the authorization code:"
                    if mode == "oauth-prompt"
                    else "Authentication failed: token expired"
                )
            ),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }))
        raise SystemExit(1)
    print(json.dumps({
        "conversation_id": "",
        "status": "SUCCESS",
        "response": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "command": {"name": "usage", "data": {"groups": [
            {"name": "Gemini Models", "buckets": [{
                "id": "gemini-weekly", "window": "weekly",
                "remaining_fraction": 0.62, "reset_time": "2033-05-20T04:33:20Z"
            }]},
            {"name": "Claude and GPT models", "buckets": [{
                "id": "3p-weekly", "window": "weekly",
                "remaining_fraction": 0.17, "reset_time": "2033-05-23T04:33:20Z"
            }]},
        ]}},
    }))
    raise SystemExit(0)

capture = Path(os.environ["AGY_ROTATION_CAPTURE"])
capture.parent.mkdir(parents=True, exist_ok=True)
token = token_path.read_text() if token_path.exists() else ""
conversation = None
if "--conversation" in args:
    conversation = args[args.index("--conversation") + 1]
fresh = "conversation-" + hashlib.sha256(token.encode()).hexdigest()[:10]
capture.write_text(capture.read_text() + json.dumps({
    "argv": args,
    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
    "conversation_arg": conversation,
}) + "\\n" if capture.exists() else json.dumps({
    "argv": args,
    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
    "conversation_arg": conversation,
}) + "\\n")
if mode == "turn-auth-error":
    print(json.dumps({"event": "result", "result": {
        "conversation_id": conversation or "",
        "status": "ERROR",
        "response": "",
        "error": "Authentication failed: token expired",
        "num_turns": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                  "thinking_tokens": 0, "total_tokens": 0},
    }}), flush=True)
    raise SystemExit(1)
print(json.dumps({"event": "init", "conversation_id": conversation or fresh,
                  "init": {"model": "gemini-3.6-flash-low", "cwd": str(home)}}), flush=True)
print(json.dumps({"event": "result", "result": {
    "conversation_id": conversation or fresh,
    "status": "SUCCESS", "response": "ok", "num_turns": 1,
    "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0,
              "thinking_tokens": 0, "total_tokens": 2},
}}), flush=True)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _canonical(auth_home: Path, token: str):
    state = auth_home / ".gemini/antigravity-cli"
    state.mkdir(parents=True, exist_ok=True)
    token_path = state / "antigravity-oauth-token"
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    return token_path


def _run_login(fake: Path, auth_home: Path, env: dict):
    assert LOGIN_SCRIPT.is_file(), "account rotation entry point is missing"
    return subprocess.run(
        [
            "bash",
            str(LOGIN_SCRIPT),
            "--agy-bin",
            str(fake),
            "--auth-home",
            str(auth_home),
        ],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


def test_t3_login_promotes_only_a_fully_validated_account(tmp_path):
    fake = tmp_path / "agy"
    auth_home = tmp_path / "auth"
    _write_fake_agy(fake)
    token_path = _canonical(auth_home, "old-token-not-real")
    old_inode = token_path.stat().st_ino

    result = _run_login(fake, auth_home, {
        "FAKE_AGY_MODE": "success",
        "FAKE_AGY_TOKEN": "new-token-not-real",
    })

    assert result.returncode == 0, result.stderr
    assert token_path.read_text() == "new-token-not-real"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert token_path.stat().st_ino != old_inode
    assert not list(tmp_path.glob(".antigravity-login.*"))
    assert "gemini-weekly" in result.stdout
    assert "3p-weekly" in result.stdout
    assert hashlib.sha256(b"new-token-not-real").hexdigest() in result.stdout


@pytest.mark.parametrize(
    "mode", ["quota-error", "eligibility-error", "oauth-prompt", "missing-model"]
)
def test_t3_failed_login_preserves_previous_credential_byte_for_byte(tmp_path, mode):
    fake = tmp_path / "agy"
    auth_home = tmp_path / "auth"
    _write_fake_agy(fake)
    token_path = _canonical(auth_home, "old-token-not-real")
    token_inode = token_path.stat().st_ino

    result = _run_login(fake, auth_home, {
        "FAKE_AGY_MODE": mode,
        "FAKE_AGY_TOKEN": "rejected-token-not-real",
    })

    assert result.returncode != 0
    assert token_path.read_text() == "old-token-not-real"
    assert token_path.stat().st_ino == token_inode
    assert not list(tmp_path.glob(".antigravity-login.*"))


def _readiness_types():
    module = importlib.import_module("app.runtime_registry")
    context_type = getattr(module, "RuntimeReadinessContext", None)
    assert context_type is not None, "#247 RuntimeReadinessContext must be merged first"
    return context_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,credentials_ready,catalog_ready",
    [
        ("success", True, True),
        ("missing-token", False, False),
        ("quota-error", False, False),
        ("eligibility-error", False, False),
        ("oauth-prompt", False, False),
        ("wrong-version", False, False),
        ("missing-model", True, False),
    ],
)
async def test_t3_runtime_readiness_checks_credentials_and_live_catalog(
    tmp_path,
    monkeypatch,
    mode,
    credentials_ready,
    catalog_ready,
):
    from app.runtime_registry import get_runtime

    module = _backend_module()
    context_type = _readiness_types()
    fake = tmp_path / "agy"
    auth_home = tmp_path / "auth"
    homes = tmp_path / "homes"
    _write_fake_agy(fake)
    if mode != "missing-token":
        _canonical(auth_home, "token-not-real")
    monkeypatch.setattr(module, "ANTIGRAVITY_BIN", str(fake))
    monkeypatch.setattr(module, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(module, "ANTIGRAVITY_HOME_ROOT", homes)
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    monkeypatch.setenv("FAKE_AGY_TOKEN", "token-not-real")

    runtime = get_runtime("antigravity")
    assert runtime.catalog_mode == "live"
    result = await runtime.readiness(context_type(
        model="antigravity/gemini-3.6-flash-low",
        profile="",
    ))

    assert result.credentials_ready is credentials_ready
    assert result.catalog_ready is catalog_ready


def test_t3_auth_generation_is_derived_from_one_atomically_promoted_token(
    tmp_path,
    monkeypatch,
):
    try:
        auth = importlib.import_module("app.antigravity_auth")
    except ModuleNotFoundError:
        auth = None
    assert auth is not None, "Antigravity auth transaction helper is missing"

    auth_home = tmp_path / "auth"
    token_path = _canonical(auth_home, "old-token-not-real")
    staged_token = tmp_path / "staged-token"
    staged_token.write_text("new-token-not-real", encoding="utf-8")
    staged_token.chmod(0o600)
    real_replace = os.replace
    replace_calls = []

    def recording_replace(source, destination):
        replace_calls.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(auth.os, "replace", recording_replace)

    old_snapshot = auth.read_auth_snapshot(auth_home)
    generation = auth.promote_staged_token(auth_home, staged_token)
    new_snapshot = auth.read_auth_snapshot(auth_home)

    assert old_snapshot.token == b"old-token-not-real"
    assert old_snapshot.generation == hashlib.sha256(old_snapshot.token).hexdigest()
    assert generation == hashlib.sha256(b"new-token-not-real").hexdigest()
    assert new_snapshot.token == b"new-token-not-real"
    assert new_snapshot.generation == generation
    assert token_path.read_bytes() == new_snapshot.token
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert replace_calls == [(staged_token, token_path)]
    assert not staged_token.exists()
    assert not (token_path.parent / "orchestra-auth-generation").exists()


def _context(tmp_path: Path, session_id: str, *, resume=None):
    from app.runtime_registry import BackendBuildContext

    return BackendBuildContext(
        model="antigravity/gemini-3.6-flash-low",
        provider="google-antigravity",
        cwd=str(tmp_path),
        system_prompt="SYSTEM",
        resume_session_id=resume,
        mcp_servers={
            "orchestra": {
                "command": "/bin/true",
                "args": [],
                "env": {"ORCHESTRA_SESSION_ID": session_id},
            },
        },
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="default",
        role="worker",
        profile="",
        effort="low",
        context_limit=128_000,
    )


@pytest.mark.asyncio
async def test_t3_account_generation_change_reuses_worker_but_not_foreign_conversation(
    tmp_path,
    monkeypatch,
):
    from app.runtime_registry import build_backend, get_runtime

    get_runtime("antigravity")
    module = _backend_module()
    fake = tmp_path / "agy"
    auth_home = tmp_path / "auth"
    homes = tmp_path / "homes"
    capture = tmp_path / "rotation.jsonl"
    _write_fake_agy(fake)
    token_path = _canonical(auth_home, "account-one-token-not-real")
    monkeypatch.setattr(module, "ANTIGRAVITY_BIN", str(fake))
    monkeypatch.setattr(module, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(module, "ANTIGRAVITY_HOME_ROOT", homes)
    monkeypatch.setenv("AGY_ROTATION_CAPTURE", str(capture))
    monkeypatch.setenv("FAKE_AGY_MODE", "success")
    backend = build_backend("antigravity", _context(
        tmp_path, "same-orchestra-worker", resume="old-account-conversation"
    ))

    await backend.connect()
    await backend.send("first")
    first_events = [event async for event in backend.events()]
    first_native_id = backend.session_id
    assert first_native_id == "old-account-conversation"

    replacement = tmp_path / "replacement-token"
    replacement.write_text("account-two-token-not-real", encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, token_path)
    await backend.send("second")
    second_events = [event async for event in backend.events()]

    rows = [json.loads(line) for line in capture.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["conversation_arg"] == "old-account-conversation"
    assert rows[1]["conversation_arg"] is None
    assert rows[0]["token_hash"] != rows[1]["token_hash"]
    assert backend.session_id != first_native_id
    assert next(event for event in second_events if event.type == "turn_end").metadata[
        "session_id"
    ] == backend.session_id
    assert first_events and second_events
    assert (homes / "same-orchestra-worker").is_dir()


@pytest.mark.asyncio
async def test_t3_post_admission_token_loss_is_terminal_visible_and_not_retried(
    tmp_path,
    monkeypatch,
):
    from app.runtime_registry import build_backend, get_runtime

    get_runtime("antigravity")
    module = _backend_module()
    fake = tmp_path / "agy"
    auth_home = tmp_path / "auth"
    homes = tmp_path / "homes"
    _write_fake_agy(fake)
    _canonical(auth_home, "expired-token-not-real")
    monkeypatch.setattr(module, "ANTIGRAVITY_BIN", str(fake))
    monkeypatch.setattr(module, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(module, "ANTIGRAVITY_HOME_ROOT", homes)
    monkeypatch.setenv("AGY_ROTATION_CAPTURE", str(tmp_path / "capture.jsonl"))
    monkeypatch.setenv("FAKE_AGY_MODE", "turn-auth-error")
    backend = build_backend(
        "antigravity", _context(tmp_path, "credential-loss-worker")
    )

    events = await asyncio.wait_for(_turn(backend, "turn"), timeout=2)

    errors = [event for event in events if event.type == "error"]
    assert len(errors) == 1
    assert "token expired" in errors[0].content
    end = next(event for event in events if event.type == "turn_end")
    assert end.metadata["ok"] is False
    assert end.metadata["model_error"] == "credentials"
    assert end.metadata["stop_reason"] == "credentials"


async def _turn(backend, message):
    await backend.connect()
    await backend.send(message)
    return [event async for event in backend.events()]


def test_t3_runbook_is_copyable_and_has_no_api_key_path():
    assert RUNBOOK.is_file(), "Antigravity account-change runbook is missing"
    text = RUNBOOK.read_text(encoding="utf-8")

    for anchor in (
        "ssh ",
        "scripts/antigravity-login.sh",
        "gemini-weekly",
        "3p-weekly",
        "новый native conversation",
        "без пересоздания Orchestra worker",
    ):
        assert anchor in text
    assert "API_KEY" not in text
    assert "GEMINI_API_KEY" not in text
    assert "AIza" not in text
