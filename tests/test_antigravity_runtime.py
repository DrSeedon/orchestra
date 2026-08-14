"""Frozen RED for #249 T1: one complete mocked Antigravity runtime slice."""

import asyncio
import importlib
import json
import os
import re
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import backend_for_model, get_model_spec, resolve_model
from app.runtime_registry import BackendBuildContext, build_backend, get_runtime

_ANTIGRAVITY_BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend_antigravity.py"
pytestmark = pytest.mark.skipif(
    not _ANTIGRAVITY_BACKEND.is_file(),
    reason="#249 phase 2 not implemented (no app/backend_antigravity.py); follow-up #279",
)


RAW_MODELS = (
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.5-flash-high",
    "gemini-3.5-flash-medium",
    "gemini-3.5-flash-low",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
)
TOKEN_SHAPED_SENTINEL = "ya29." + "A" * 64


def _runtime():
    try:
        runtime = get_runtime("antigravity")
    except ValueError:
        runtime = None
    assert runtime is not None, "Antigravity runtime is not registered"
    return runtime


def _backend_module():
    try:
        module = importlib.import_module("app.backend_antigravity")
    except ModuleNotFoundError:
        module = None
    assert module is not None, "Antigravity backend module is missing"
    return module


def test_t1_namespaced_model_surface_and_runtime_capabilities_are_exact():
    runtime = _runtime()

    assert tuple(
        model_id for model_id in (f"antigravity/{raw}" for raw in RAW_MODELS)
        if backend_for_model(model_id) == "antigravity"
    ) == tuple(f"antigravity/{raw}" for raw in RAW_MODELS)
    for raw in RAW_MODELS:
        spec = get_model_spec(f"antigravity/{raw}")
        assert spec.runtime == "antigravity"
        assert spec.provider == "google-antigravity"
        assert spec.context_length == 128_000

    assert resolve_model("agy-flash") == "antigravity/gemini-3.6-flash-low"
    assert resolve_model("agy-pro") == "antigravity/gemini-3.1-pro-low"
    assert resolve_model("agy-sonnet") == "antigravity/claude-sonnet-4-6"
    assert resolve_model("agy-opus") == "antigravity/claude-opus-4-6-thinking"
    assert resolve_model("agy-gptoss") == "antigravity/gpt-oss-120b-medium"
    # The new surface must not steal the existing Claude upgrade alias.
    assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-5[1m]"
    assert backend_for_model(resolve_model("claude-sonnet-4-6")) == "claude"

    assert runtime.capabilities.to_dict() == {
        "event_stream": "per_turn",
        "mid_turn_inject": False,
        "reconnect": False,
        "hibernate": False,
        "process_liveness": True,
        "resume": True,
        "resume_across_models": False,
        "subagents": False,
    }


def _fake_agy(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys
import time

args = sys.argv[1:]
home = Path(os.environ["HOME"])
capture_root = Path(os.environ["AGY_TEST_CAPTURE"])
capture_root.mkdir(parents=True, exist_ok=True)
token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
agent = home / ".gemini/config/agents/orchestra/agent.md"
settings = home / ".gemini/antigravity-cli/settings.json"
mcp = home / ".gemini/config/mcp_config.json"
mcp_data = json.loads(mcp.read_text()) if mcp.exists() else None
marker = home.name
conversation = None
if "--conversation" in args:
    conversation = args[args.index("--conversation") + 1]
if conversation is None:
    conversation = "conversation-" + marker
prompt = args[args.index("-p") + 1]
(home / ".gemini/antigravity-cli/scratch").mkdir(parents=True, exist_ok=True)
(home / ".gemini/antigravity-cli/scratch/same-name.txt").write_text(marker)
(capture_root / (marker + ".json")).write_text(json.dumps({
    "argv": args,
    "home": str(home),
    "token_present": token.is_file(),
    "token_mode": oct(token.stat().st_mode & 0o777) if token.exists() else None,
    "agent": agent.read_text() if agent.exists() else None,
    "agent_mode": oct(agent.stat().st_mode & 0o777) if agent.exists() else None,
    "settings": json.loads(settings.read_text()) if settings.exists() else None,
    "settings_mode": oct(settings.stat().st_mode & 0o777) if settings.exists() else None,
    "mcp": mcp_data,
    "mcp_mode": oct(mcp.stat().st_mode & 0o777) if mcp.exists() else None,
}))
if mcp_data:
    print("vendor-stderr:" + mcp_data["mcpServers"]["orchestra"]["env"]["INTERNAL_TOKEN"],
          file=sys.stderr, flush=True)
if prompt == "BLOCK":
    time.sleep(30)
    raise SystemExit(0)
print(json.dumps({
    "event": "init",
    "conversation_id": conversation,
    "init": {"model": "gemini-3.6-flash-low", "cwd": args[args.index("--add-dir") + 1]},
}), flush=True)
print(json.dumps({
    "event": "step_update",
    "step_update": {
        "conversation_id": conversation,
        "step_index": 2,
        "state": "ACTIVE",
        "step_type": "agent_response",
        "text_delta": "stream-one ",
    },
}), flush=True)
print(json.dumps({
    "event": "step_update",
    "step_update": {
        "conversation_id": conversation,
        "step_index": 3,
        "state": "ACTIVE",
        "step_type": "tool",
        "tool_name": "call_mcp_tool",
        "tool_info": {"name": "call_mcp_tool", "parameters": {
            "ServerName": "orchestra", "ToolName": "list_agents", "Arguments": {}
        }},
    },
}), flush=True)
tool_error = prompt == "TOOL_ERROR"
tool_info = {"name": "call_mcp_tool", "parameters": {
    "ServerName": "orchestra", "ToolName": "list_agents", "Arguments": {}
}}
if tool_error:
    tool_info["error"] = {"type": "TOOL_ERROR", "message": "credential vanished"}
else:
    tool_info["output"] = "MCP-OK"
print(json.dumps({
    "event": "step_update",
    "step_update": {
        "conversation_id": conversation,
        "step_index": 3,
        "state": "ERROR" if tool_error else "DONE",
        "step_type": "tool",
        "tool_name": "call_mcp_tool",
        "tool_info": tool_info,
    },
}), flush=True)
print(json.dumps({
    "event": "step_update",
    "step_update": {
        "conversation_id": conversation,
        "step_index": 4,
        "state": "DONE",
        "step_type": "agent_response",
        "text_delta": "stream-two",
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 75},
    },
}), flush=True)
print(json.dumps({
    "event": "result",
    "result": {
        "conversation_id": conversation,
        "status": "SUCCESS",
        "response": "FINAL-" + marker,
        "num_turns": 1,
        "usage": {
            "input_tokens": 123,
            "output_tokens": 24,
            "thinking_tokens": 7,
            "cache_read_tokens": 81,
            "total_tokens": 147,
        },
    },
}), flush=True)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _seed_auth(auth_home: Path, token="oauth-token-not-real"):
    root = auth_home / ".gemini/antigravity-cli"
    root.mkdir(parents=True)
    token_path = root / "antigravity-oauth-token"
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)


def _context(cwd: Path, session_id: str, *, resume=None, system_prompt=None):
    return BackendBuildContext(
        model="antigravity/gemini-3.6-flash-low",
        provider="google-antigravity",
        cwd=str(cwd),
        system_prompt=system_prompt or f"SYSTEM-{session_id}",
        resume_session_id=resume,
        mcp_servers={
            "orchestra": {
                "command": "/opt/orchestra/python",
                "args": ["/opt/orchestra/mcp_stdio.py"],
                "env": {
                    "ORCHESTRA_SESSION_ID": session_id,
                    "INTERNAL_TOKEN": TOKEN_SHAPED_SENTINEL,
                },
            },
        },
        is_orchestrator=False,
        scope=str(cwd),
        pipeline="default",
        role="worker",
        profile="",
        effort="low",
        context_limit=128_000,
    )


def _configure(monkeypatch, tmp_path):
    _runtime()
    module = _backend_module()
    fake = tmp_path / "agy"
    capture = tmp_path / "capture"
    auth_home = tmp_path / "canonical-auth"
    homes = tmp_path / "worker-homes"
    _fake_agy(fake)
    _seed_auth(auth_home)
    monkeypatch.setattr(module, "ANTIGRAVITY_BIN", str(fake))
    monkeypatch.setattr(module, "ANTIGRAVITY_AUTH_HOME", auth_home)
    monkeypatch.setattr(module, "ANTIGRAVITY_HOME_ROOT", homes)
    monkeypatch.setenv("AGY_TEST_CAPTURE", str(capture))
    return module, capture, auth_home, homes


async def _turn(backend, message):
    await backend.connect()
    await backend.send(message)
    return [event async for event in backend.events()]


@pytest.mark.asyncio
async def test_t1_two_workers_stream_tools_resume_and_keep_every_state_path_private(
    tmp_path,
    monkeypatch,
    caplog,
):
    caplog.set_level("DEBUG")
    assert re.fullmatch(r"ya29\.[A-Za-z0-9_-]{40,}", TOKEN_SHAPED_SENTINEL)
    _module, capture, _auth_home, homes = _configure(monkeypatch, tmp_path)
    cwd_a = tmp_path / "work-a"
    cwd_b = tmp_path / "work-b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    backend_a = build_backend("antigravity", _context(cwd_a, "session-a"))
    backend_b = build_backend(
        "antigravity",
        _context(cwd_b, "session-b", resume="resume-b-exact"),
    )

    events_a, events_b = await asyncio.gather(
        _turn(backend_a, "NORMAL-A"),
        _turn(backend_b, "NORMAL-B"),
    )

    assert backend_a.session_id == "conversation-session-a"
    assert backend_b.session_id == "resume-b-exact"
    assert (homes / "session-a" / ".gemini/antigravity-cli/scratch/same-name.txt").read_text() == "session-a"
    assert (homes / "session-b" / ".gemini/antigravity-cli/scratch/same-name.txt").read_text() == "session-b"
    assert stat.S_IMODE((homes / "session-a").stat().st_mode) == 0o700
    assert stat.S_IMODE((homes / "session-b").stat().st_mode) == 0o700

    for session_id, cwd, events in (
        ("session-a", cwd_a, events_a),
        ("session-b", cwd_b, events_b),
    ):
        captured = json.loads((capture / f"{session_id}.json").read_text())
        argv = captured["argv"]
        assert argv[:2] == ["--output-format", "stream-json"]
        assert argv[argv.index("--model") + 1] == "gemini-3.6-flash-low"
        assert argv[argv.index("--agent") + 1] == "orchestra"
        assert argv[argv.index("--add-dir") + 1] == str(cwd)
        assert "--dangerously-skip-permissions" not in argv
        assert "-c" not in argv
        if session_id == "session-b":
            assert argv[argv.index("--conversation") + 1] == "resume-b-exact"
        else:
            assert "--conversation" not in argv
        assert captured["token_present"] is True
        assert captured["token_mode"] == "0o600"
        assert captured["agent_mode"] == "0o600"
        assert captured["settings_mode"] == "0o600"
        assert captured["mcp_mode"] == "0o600"
        assert f"SYSTEM-{session_id}" in captured["agent"]
        assert captured["mcp"] == {
            "mcpServers": {
                "orchestra": {
                    "command": "/opt/orchestra/python",
                    "args": ["/opt/orchestra/mcp_stdio.py"],
                    "env": {
                        "ORCHESTRA_SESSION_ID": session_id,
                        "INTERNAL_TOKEN": TOKEN_SHAPED_SENTINEL,
                    },
                },
            },
        }
        assert captured["settings"]["permission"]["allow"] == [
            "command(*)",
            "read_file(*)",
            "write_file(*)",
            "mcp(*)",
        ]
        for anchor in (
            "mainAgent: true",
            "subagent: false",
            "inheritMcp: true",
            "commandExecutionPolicy: always-proceed",
        ):
            assert anchor in captured["agent"]
        serialized_argv = json.dumps(argv)
        assert TOKEN_SHAPED_SENTINEL not in serialized_argv
        assert all(
            TOKEN_SHAPED_SENTINEL not in event.content for event in events
        )
        assert [event.content for event in events if event.type == "stream"] == [
            "stream-one ",
            "stream-two",
        ]
        assert [event.content for event in events if event.type == "text"] == [
            f"FINAL-{session_id}"
        ]
        tool_use = next(event for event in events if event.type == "tool_use")
        tool_result = next(event for event in events if event.type == "tool_result")
        assert tool_use.metadata["tool_use_id"] == tool_result.metadata["tool_use_id"]
        assert tool_result.content == "MCP-OK"
        assert tool_result.metadata["is_error"] is False
        end = next(event for event in events if event.type == "turn_end")
        expected_session_id = (
            backend_a.session_id if session_id == "session-a" else backend_b.session_id
        )
        assert end.metadata["session_id"] == expected_session_id
        assert end.metadata["ok"] is True
        assert end.metadata["cost_unaccounted"] is True
        assert end.usage.aggregate.input_tokens == 123
        assert end.usage.aggregate.output_tokens == 24
        assert end.usage.aggregate.cache_read_tokens == 81
        assert end.usage.current.reason == "Antigravity did not report current-context semantics"
        assert not (
            homes / session_id / ".gemini/antigravity-cli/antigravity-oauth-token"
        ).exists()
    assert TOKEN_SHAPED_SENTINEL not in caplog.text


@pytest.mark.asyncio
async def test_t1_tool_error_overrides_terminal_success_and_is_not_silent(
    tmp_path,
    monkeypatch,
):
    _configure(monkeypatch, tmp_path)
    cwd = tmp_path / "work"
    cwd.mkdir()
    backend = build_backend("antigravity", _context(cwd, "tool-error-session"))

    events = await _turn(backend, "TOOL_ERROR")

    failed_tool = next(event for event in events if event.type == "tool_result")
    assert failed_tool.metadata["is_error"] is True
    assert "credential vanished" in failed_tool.content
    assert any(event.type == "error" and "credential vanished" in event.content for event in events)
    end = next(event for event in events if event.type == "turn_end")
    assert end.metadata["ok"] is False
    assert end.metadata["stop_reason"] == "tool_error"


@pytest.mark.asyncio
async def test_t1_interrupt_terminates_only_owned_process_and_cleans_token(
    tmp_path,
    monkeypatch,
):
    _module, capture, _auth_home, _homes = _configure(monkeypatch, tmp_path)
    cwd = tmp_path / "work"
    cwd.mkdir()
    unrelated_home = tmp_path / "unrelated-home"
    unrelated_home.mkdir()
    unrelated = subprocess.Popen(
        [
            str(tmp_path / "agy"),
            "--output-format", "stream-json",
            "--model", "gemini-3.6-flash-low",
            "--agent", "orchestra",
            "--add-dir", str(cwd),
            "-p", "BLOCK",
        ],
        cwd=cwd,
        env={
            **os.environ,
            "HOME": str(unrelated_home),
            "AGY_TEST_CAPTURE": str(capture),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    unrelated_started = capture / "unrelated-home.json"
    for _ in range(200):
        if unrelated_started.is_file():
            break
        time.sleep(0.01)
    assert unrelated_started.is_file(), "unrelated fake process did not enter its body"
    backend = build_backend("antigravity", _context(cwd, "interrupt-session"))
    try:
        await backend.connect()
        await backend.send("BLOCK")

        assert backend.is_alive is True
        assert await backend.interrupt() is True
        events = [event async for event in backend.events()]

        assert backend.is_alive is False
        assert unrelated.poll() is None
        assert next(event for event in events if event.type == "turn_end").metadata == {
            "session_id": None,
            "ok": False,
            "stop_reason": "interrupt",
            "cost_usd": 0.0,
            "cost_unaccounted": True,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cache_read": 0,
            "cache_create": 0,
            "model_error": "interrupted",
            "errors": ["interrupted"],
        }
        assert not (
            tmp_path
            / "worker-homes/interrupt-session/.gemini/antigravity-cli/antigravity-oauth-token"
        ).exists()
    finally:
        unrelated.terminate()
        try:
            unrelated.wait(timeout=2)
        except subprocess.TimeoutExpired:
            unrelated.kill()
            unrelated.wait(timeout=2)


@pytest.mark.asyncio
async def test_t1_antigravity_manual_compact_uses_summary_then_force_fresh(
    tmp_path,
    monkeypatch,
):
    _runtime()
    from app.events import AgentEvent
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: True)
    summary = "TASK STATE: Antigravity summary survives compact. " + "x" * 260

    class SummaryBackend:
        session_id = "summary-native-id"

        def __init__(self):
            self.sent = []

        async def connect(self):
            return None

        async def send(self, message):
            self.sent.append(message)

        async def events(self):
            yield AgentEvent("text", summary)
            yield AgentEvent("turn_end", metadata={
                "session_id": self.session_id,
                "ok": True,
                "stop_reason": "end_turn",
                "num_turns": 1,
            })

        async def disconnect(self):
            return None

    summary_backend = SummaryBackend()
    fresh_backend = AsyncMock()
    fresh_backend.session_id = "fresh-antigravity-id"
    force_fresh_calls = []
    session = AgentSession(
        id="compact-antigravity",
        name="agy-compact",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="antigravity/gemini-3.6-flash-low",
        backend_type="antigravity",
        system_prompt="SYSTEM",
        created_at=datetime.now(timezone.utc),
    )
    session.is_orchestrator = True
    session.session_id = "old-antigravity-id"
    session.status = AgentStatus.IDLE
    session._log = MagicMock()
    session._make_backend = MagicMock(return_value=summary_backend)

    async def ensure_backend(force_fresh=False):
        force_fresh_calls.append(force_fresh)
        assert force_fresh is True
        session._backend = fresh_backend

        async def finish_ack():
            await asyncio.sleep(0)
            session.session_id = "fresh-antigravity-id"
            session.status = AgentStatus.IDLE
            session._compact_ack_event.set()

        asyncio.create_task(finish_ack())
        return fresh_backend

    session._ensure_backend = ensure_backend

    result = await session.compact()

    assert result["ok"] is True
    assert summary_backend.sent and "Context compaction requested" in summary_backend.sent[0]
    assert force_fresh_calls == [True]
    fresh_backend.send.assert_awaited_once()
    assert summary in fresh_backend.send.await_args.args[0]
    assert session.session_id == "fresh-antigravity-id"
    assert session.session_id_history[-1]["session_id"] == "old-antigravity-id"
