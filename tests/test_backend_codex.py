"""CodexBackend — model dicts, runtime accounting, and per-worker MCP config.

Regression net for the three bugs found in the codex-integration audit:
  BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
  BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
  MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.backend_codex import (
    CodexBackend,
    CODEX_CONTEXT_LIMITS,
    CODEX_TOKEN_PRICES,
    CODEX_REASONING_EFFORTS,
    _codex_cost,
    _read_rollout_context,
    _usage_delta,
)


# ── BUG 1: GPT-5.6 models registered in backend dicts ──

def test_gpt56_context_limits_present():
    # ChatGPT-auth Codex runtime reports a 258400 effective budget for these models.
    # The public API's 1.05M window is a different surface and must not drive dashboard
    # accounting or auto-compact for a local Codex worker.
    for m in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert CODEX_CONTEXT_LIMITS[m] == 258400, m


def test_gpt56_prices_present():
    assert CODEX_TOKEN_PRICES["gpt-5.6-sol"] == {"input": 5.0, "cached": 0.5, "output": 30.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {"input": 2.5, "cached": 0.25, "output": 15.0}
    assert CODEX_TOKEN_PRICES["gpt-5.6-luna"] == {"input": 1.0, "cached": 0.1, "output": 6.0}


def test_legacy_gpt_models_unchanged():
    assert CODEX_CONTEXT_LIMITS["gpt-5.5"] == 258400
    assert CODEX_TOKEN_PRICES["gpt-5.4"] == {"input": 2.5, "cached": 0.25, "output": 15.0}


def test_sol_price_and_ctx_not_zero_fallback():
    # Sol has an explicit runtime limit and price rather than relying on fallbacks.
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert CODEX_CONTEXT_LIMITS[b.model] == 258400
    assert CODEX_TOKEN_PRICES[b.model]["output"] == 30.0


def test_codex_cost_applies_cached_input_discount():
    # 100 fresh × $5/M + 900 cached × $0.5/M + 10 output × $30/M.
    assert _codex_cost("gpt-5.6-sol", 1000, 900, 10) == pytest.approx(0.00125)


def test_usage_delta_survives_resume_and_counter_reset():
    current = {"input_tokens": 130, "cached_input_tokens": 90, "output_tokens": 20}
    baseline = {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 5}
    assert _usage_delta(current, baseline) == {
        "input_tokens": 30, "cached_input_tokens": 10, "output_tokens": 15,
    }
    # A Codex-side compact may reset counters. Treat the new value as this turn rather
    # than producing negative usage or zeroing a real call.
    assert _usage_delta({"input_tokens": 10}, {"input_tokens": 100})["input_tokens"] == 10


def test_rollout_context_uses_last_call_not_accumulated_usage(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 760838},
            "last_token_usage": {"input_tokens": 95489, "cached_input_tokens": 92928},
            "model_context_window": 258400,
        }}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 2042411},
            "last_token_usage": {"input_tokens": 142165, "cached_input_tokens": 141056},
            "model_context_window": 258400,
        }}},
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert _read_rollout_context(rollout) == {
        "input_tokens": 142165,
        "cached_input_tokens": 141056,
        "model_context_window": 258400,
    }


def test_rollout_context_fails_soft_on_missing_or_corrupt_data(tmp_path):
    assert _read_rollout_context(tmp_path / "missing.jsonl") is None
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not-json\n{}\n")
    assert _read_rollout_context(corrupt) is None


# ── BUG 2: reasoning effort ──

def test_xhigh_and_max_accepted():
    assert "xhigh" in CODEX_REASONING_EFFORTS
    assert "max" in CODEX_REASONING_EFFORTS


def test_effort_passthrough_and_fallback():
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="xhigh").reasoning_effort == "xhigh"
    # unknown value falls back to high, never crashes
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp", reasoning_effort="bogus").reasoning_effort == "high"


# ── Per-worker MCP config (dotted-leaf -c overrides) ──

def test_mcp_config_args_dotted_leaves():
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
        "orchestra": {
            "command": "python",
            "args": ["/x/mcp_stdio.py"],
            "env": {"WORKER_NAME": "w1"},
        },
    })
    args = b._mcp_config_args()
    # dotted-leaf form — Codex rejects a whole-table value as a string
    assert 'mcp_servers.orchestra.command="python"' in args
    assert 'mcp_servers.orchestra.args=["/x/mcp_stdio.py"]' in args
    assert 'mcp_servers.orchestra.env={WORKER_NAME="w1"}' in args
    assert "mcp_servers.orchestra.enabled=true" in args
    enabled_tools = next(a for a in args if a.startswith("mcp_servers.orchestra.enabled_tools="))
    assert '"send_message"' in enabled_tools
    assert '"spawn_worker"' in enabled_tools


def test_mcp_config_supports_url_only_servers():
    b = CodexBackend(model="gpt-5.6-sol", cwd="/tmp", mcp_servers={
        "remote": {"url": "https://example/sse"},
    })
    args = b._mcp_config_args()
    assert "mcp_servers.remote.enabled=true" in args
    assert 'mcp_servers.remote.url="https://example/sse"' in args


def test_mcp_config_empty_when_no_servers():
    assert CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._mcp_config_args() == []


def test_toml_str_escapes():
    assert CodexBackend._toml_str('a"b\\c') == '"a\\"b\\\\c"'


def test_codex_inherits_orchestra_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:12343")
    env = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._build_env()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:12343"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:12343"


@pytest.mark.asyncio
async def test_thread_started_exposes_session_id_before_turn_completion():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "thread/started",
        "params": {"thread": {"id": "thread-early"}},
    })
    event = events[0]

    assert event.type == "status"
    assert event.metadata["session_id"] == "thread-early"


@pytest.mark.asyncio
async def test_send_steers_active_app_server_turn():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"
    backend._request = AsyncMock(return_value={"turnId": "turn-1"})

    await backend.send("extra context")

    backend._request.assert_awaited_once_with("turn/steer", {
        "threadId": "thread-1",
        "expectedTurnId": "turn-1",
        "input": [{"type": "text", "text": "extra context"}],
    })


@pytest.mark.asyncio
async def test_send_starts_turn_when_idle():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._request = AsyncMock(return_value={"turn": {"id": "turn-2"}})

    await backend.send("do it")

    backend._request.assert_awaited_once_with("turn/start", {
        "threadId": "thread-1",
        "input": [{"type": "text", "text": "do it"}],
        "model": "gpt-5.6-sol",
        "effort": "high",
    })
    assert backend._active_turn_id == "turn-2"


def test_app_server_events_cover_web_reasoning_and_network_failure():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    web = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {"id": "web-1", "type": "webSearch", "query": "official Codex docs"},
        },
    })
    assert web[0].type == "tool_use"
    assert web[0].metadata["short_name"] == "WebSearch"

    reasoning = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "reason-1",
                "type": "reasoning",
                "summary": ["Inspecting runtime", "Checking transport"],
                "content": [],
            },
        },
    })
    assert reasoning[0].type == "thinking"
    assert "Checking transport" in reasoning[0].content

    backend._last_turn_error = {
        "message": "stream disconnected",
        "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": None}},
    }
    failed = backend._convert_notification({
        "method": "turn/completed",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": "turn-1", "status": "failed", "items": []},
        },
    })
    end = next(event for event in failed if event.type == "turn_end")
    assert end.metadata["ok"] is False
    assert end.metadata["model_error"] == "server_error"


def test_collab_agent_event_is_visible_as_subagent():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-1",
                "type": "collabAgentToolCall",
                "tool": "spawnAgent",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {},
                "status": "inProgress",
                "prompt": "Research the API",
            },
        },
    })
    assert events[0].type == "subagent_start"
    assert events[0].metadata["subagent_id"] == "child-1"


def test_completed_collab_wait_emits_subagent_end_for_terminal_agent():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "collab-2",
                "type": "collabAgentToolCall",
                "tool": "wait",
                "receiverThreadIds": ["child-1"],
                "senderThreadId": "thread-1",
                "agentsStates": {"child-1": {"status": "completed", "message": "Done"}},
                "status": "completed",
            },
        },
    })

    assert events[0].type == "subagent_end"
    assert events[0].metadata["status"] == "completed"


def test_agent_message_delta_is_streamed_to_frontend():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    events = backend._convert_notification({
        "method": "item/agentMessage/delta",
        "params": {"threadId": "thread-1", "turnId": "turn-1", "delta": "partial"},
    })

    assert [(event.type, event.content) for event in events] == [("stream", "partial")]


def test_is_alive_tracks_codex_process_state():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert backend.is_alive is False

    backend._proc = SimpleNamespace(returncode=None)
    assert backend.is_alive is True

    backend._proc.returncode = 0
    assert backend.is_alive is False
