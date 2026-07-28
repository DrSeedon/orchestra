"""CodexBackend — model dicts, runtime accounting, and per-worker MCP config.

Regression net for the three bugs found in the codex-integration audit:
  BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
  BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
  MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
"""

import asyncio
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


def test_spark_context_limit_matches_local_codex_metadata():
    assert CODEX_CONTEXT_LIMITS["gpt-5.3-codex-spark"] == 128000


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


@pytest.mark.asyncio
async def test_events_reject_stale_lifecycle_without_losing_current_turn(caplog):
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "task-turn"

    for method, turn_id in (
        ("turn/started", "compact-turn"),
        ("turn/completed", "compact-turn"),
        ("turn/started", "task-turn"),
    ):
        await backend._notifications.put({
            "method": method,
            "params": {"threadId": "thread-1", "turn": {"id": turn_id}},
        })
    await backend._notifications.put({
        "method": "item/agentMessage/delta",
        "params": {"threadId": "thread-1", "delta": "FIRST_PROCESSED"},
    })
    await backend._notifications.put({
        "method": "turn/completed",
        "params": {
            "threadId": "thread-1",
            "turn": {"id": "task-turn", "status": "completed"},
        },
    })

    with caplog.at_level("DEBUG", logger="app.backend_codex"):
        events = [event async for event in backend.events()]

    assert any(event.type == "stream" and event.content == "FIRST_PROCESSED"
               for event in events)
    assert [event.type for event in events].count("turn_end") == 1
    assert "compact-turn" in caplog.text
    assert "task-turn" in caplog.text
    assert "turn/started" in caplog.text
    assert "turn/completed" in caplog.text
    assert backend._active_turn_id is None


@pytest.mark.asyncio
async def test_native_compact_drains_terminal_before_returning():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_id = "thread-1"
    stdout = asyncio.StreamReader()
    backend._proc = SimpleNamespace(
        returncode=None,
        stdout=stdout,
        wait=AsyncMock(return_value=0),
    )
    backend._reader_task = asyncio.create_task(backend._read_stdout())
    request_started = asyncio.Event()
    compact_queue_was_attached = []

    def feed(message):
        stdout.feed_data((json.dumps(message) + "\n").encode())

    async def request(method, params):
        compact_queue_was_attached.append(
            getattr(backend, "_compact_notifications", None) is not None
        )
        feed({
            "method": "turn/started",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "compact-turn"},
            },
        })
        feed({
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "tokenUsage": {
                    "last": {"totalTokens": 33_124},
                    "total": {},
                    "modelContextWindow": 258_400,
                },
            },
        })
        feed({
            "method": "item/completed",
            "params": {
                "threadId": "thread-1",
                "item": {"type": "contextCompaction", "id": "compact-1"},
            },
        })
        request_started.set()
        return {}

    backend._request = AsyncMock(side_effect=request)
    task = asyncio.create_task(backend.compact_context())
    try:
        await asyncio.wait_for(request_started.wait(), timeout=0.5)
        done, _ = await asyncio.wait({task}, timeout=0.05)
        assert task not in done

        feed({
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "compact-turn", "status": "completed"},
            },
        })
        result = await asyncio.wait_for(task, timeout=0.5)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        backend._disconnecting = True
        stdout.feed_eof()
        await asyncio.wait_for(backend._reader_task, timeout=0.5)

    backend._request.assert_awaited_once_with(
        "thread/compact/start",
        {"threadId": "thread-1"},
    )
    assert compact_queue_was_attached == [True]
    assert backend._notifications.empty()
    assert backend._compact_notifications is None
    assert backend.session_id == "thread-1"
    assert result == {
        "ok": True,
        "thread_id": "thread-1",
        "context_tokens": 33_124,
        "max_tokens": 258_400,
    }


@pytest.mark.asyncio
async def test_native_compact_missing_terminal_times_out_and_detaches(monkeypatch):
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_id = "thread-1"
    stdout = asyncio.StreamReader()
    backend._proc = SimpleNamespace(
        returncode=None,
        stdout=stdout,
        wait=AsyncMock(return_value=0),
    )
    backend._reader_task = asyncio.create_task(backend._read_stdout())
    monkeypatch.setattr("app.backend_codex.CODEX_COMPACT_TIMEOUT_SECONDS", 0.03)

    async def request(_method, _params):
        for message in (
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "compact-turn"},
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "item": {"type": "contextCompaction", "id": "compact-1"},
                },
            },
        ):
            stdout.feed_data((json.dumps(message) + "\n").encode())
        return {}

    backend._request = AsyncMock(side_effect=request)
    try:
        with pytest.raises(TimeoutError):
            await backend.compact_context()
    finally:
        backend._disconnecting = True
        stdout.feed_eof()
        await asyncio.wait_for(backend._reader_task, timeout=0.5)

    assert backend._compact_notifications is None
    assert backend._notifications.empty()


@pytest.mark.asyncio
async def test_native_compact_rejects_active_turn():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"

    with pytest.raises(RuntimeError, match="active turn"):
        await backend.compact_context()


@pytest.mark.asyncio
async def test_silent_active_turn_emits_transient_heartbeat():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1"
    backend._active_turn_id = "turn-1"
    backend._notifications = SimpleNamespace(
        get=AsyncMock(side_effect=asyncio.TimeoutError),
    )

    iterator = backend.events()
    event = await anext(iterator)
    await iterator.aclose()

    assert event.type == "thinking_stream"
    assert event.metadata == {"activity": "waiting", "item_id": "turn-1"}
    assert "still working" in event.content.lower()


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


def test_command_execution_exposes_actions_and_live_output():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    started = backend._convert_notification({
        "method": "item/started",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "id": "cmd-1",
                "type": "commandExecution",
                "command": "rg -n TODO app",
                "commandActions": [{
                    "type": "search",
                    "command": "rg -n TODO app",
                    "path": "app",
                    "query": "TODO",
                }],
                "cwd": "/tmp",
                "status": "inProgress",
            },
        },
    })
    live = backend._convert_notification({
        "method": "item/commandExecution/outputDelta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "cmd-1",
            "delta": "app/main.py:4:TODO\n",
        },
    })

    assert started[0].type == "tool_use"
    assert started[0].metadata["tool_name"] == "Bash"
    command_payload = json.loads(started[0].content.split(": ", 1)[1])
    assert command_payload["command"] == "rg -n TODO app"
    assert command_payload["command_actions"][0]["type"] == "search"
    assert live[0].type == "tool_stream"
    assert live[0].metadata["tool_use_id"] == "cmd-1"


def test_file_change_exposes_unified_diff_and_patch_updates():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    item = {
        "id": "patch-1",
        "type": "fileChange",
        "changes": [{
            "path": "/tmp/app.py",
            "kind": "update",
            "diff": "@@ -1 +1 @@\n-old\n+new\n",
        }],
        "status": "inProgress",
    }
    started = backend._convert_notification({
        "method": "item/started",
        "params": {"threadId": "thread-1", "turnId": "turn-1", "item": item},
    })
    patch = backend._convert_notification({
        "method": "item/fileChange/patchUpdated",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "patch-1",
            "changes": item["changes"],
        },
    })
    completed = backend._convert_notification({
        "method": "item/completed",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {**item, "status": "completed"},
        },
    })

    assert started[0].metadata["tool_name"] == "FileChange"
    assert json.loads(started[0].content.split(": ", 1)[1])["changes"][0]["diff"]
    assert patch[0].type == "tool_patch"
    assert patch[0].metadata["tool_use_id"] == "patch-1"
    assert completed[0].type == "tool_result"
    assert json.loads(completed[0].content)["status"] == "completed"


def test_completed_turn_id_is_carried_as_durable_event_id():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._turn_completed({
        "id": "turn-1",
        "status": "completed",
    })

    assert events[-1].metadata["event_id"] == "turn-1"


def test_turn_usage_keeps_codex_delta_and_last_call_context_distinct():
    from app.usage_contract import KnownContext

    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_usage_total = {
        "input_tokens": 100_000,
        "cached_input_tokens": 80_000,
        "output_tokens": 2_000,
    }
    backend._usage_baseline = {
        "input_tokens": 40_000,
        "cached_input_tokens": 30_000,
        "output_tokens": 500,
    }
    backend._last_call_usage = {
        "input_tokens": 33_124,
        "model_context_window": 258_400,
    }

    end = backend._turn_completed({
        "id": "turn-usage",
        "status": "completed",
    })[-1]

    assert end.usage.aggregate.input_tokens == 60_000
    assert isinstance(end.usage.current, KnownContext)
    assert end.metadata["context_tokens"] == 33_124
    assert end.metadata["context_known"] is True


def test_explicit_codex_tool_failures_keep_identity_and_tool_name():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    command = backend._item_completed({
        "id": "cmd-1",
        "type": "commandExecution",
        "command": "false",
        "aggregatedOutput": "exit 1",
        "exitCode": 1,
    })
    mcp = backend._item_completed({
        "id": "mcp-1",
        "type": "mcpToolCall",
        "server": "orchestra",
        "tool": "send_message",
        "arguments": {},
        "error": {"message": "delivery failed"},
    })
    dynamic = backend._item_completed({
        "id": "dynamic-1",
        "type": "dynamicToolCall",
        "tool": "custom",
        "status": "failed",
        "success": False,
    })

    failures = [
        event
        for event in command + mcp + dynamic
        if event.type == "tool_result" and event.metadata.get("is_error")
    ]
    assert [(event.metadata["tool_use_id"], event.metadata["tool_name"]) for event in failures] == [
        ("cmd-1", "Bash"),
        ("mcp-1", "mcp__orchestra__send_message"),
        ("dynamic-1", "custom"),
    ]


def test_reasoning_plan_warning_compaction_and_mcp_failure_telemetry():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")

    reasoning = backend._convert_notification({
        "method": "item/reasoning/summaryTextDelta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "reason-1",
            "summaryIndex": 0,
            "delta": "Checking contracts",
        },
    })
    plan_delta = backend._convert_notification({
        "method": "item/plan/delta",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "plan-1",
            "delta": "1. Inspect UI",
        },
    })
    plan = backend._convert_notification({
        "method": "turn/plan/updated",
        "params": {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "explanation": "Parity pass",
            "plan": [
                {"step": "Inspect UI", "status": "completed"},
                {"step": "Patch renderer", "status": "inProgress"},
            ],
        },
    })
    warning = backend._convert_notification({
        "method": "warning",
        "params": {"threadId": "thread-1", "message": "Transport is degraded"},
    })
    compacted = backend._convert_notification({
        "method": "thread/compacted",
        "params": {"threadId": "thread-1"},
    })
    mcp_starting = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "starting",
        },
    })
    mcp_ready = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "ready",
        },
    })
    mcp_failed = backend._convert_notification({
        "method": "mcpServer/startupStatus/updated",
        "params": {
            "threadId": "thread-1",
            "name": "orchestra",
            "status": "failed",
            "failureReason": "process exited",
        },
    })

    assert reasoning[0].type == "thinking_stream"
    assert reasoning[0].metadata["activity"] == "reasoning"
    assert plan_delta[0].type == "thinking_stream"
    assert plan_delta[0].metadata["activity"] == "plan"
    assert plan[0].type == "plan"
    assert json.loads(plan[0].content)["plan"][1]["status"] == "inProgress"
    assert warning[0].type == "warning"
    assert compacted[0].content == "codex context compacted"
    assert mcp_starting == []
    assert mcp_ready == []
    assert mcp_failed[0].type == "warning"
    assert mcp_failed[0].content == "codex mcp orchestra: failed — process exited"


def test_long_mcp_arguments_remain_valid_structured_json():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    events = backend._convert_notification({
        "method": "item/started",
        "params": {
            "item": {
                "id": "spawn-1",
                "type": "mcpToolCall",
                "server": "orchestra",
                "tool": "spawn_worker",
                "arguments": {
                    "name": "mobile-os-strategy",
                    "model": "gpt-5.6-sol",
                    "task": "Research the mobile OS strategy",
                    "system_prompt": "Detailed worker instructions. " * 200,
                },
            },
        },
    })

    assert len(events) == 1
    payload = json.loads(events[0].content.split(": ", 1)[1])
    assert payload["name"] == "mobile-os-strategy"
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["task"] == "Research the mobile OS strategy"
    assert payload["system_prompt"].startswith("Detailed worker instructions.")
    assert payload["_codex_item_id"] == "spawn-1"


def test_collab_terminal_event_keeps_spawn_description_and_summary():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._convert_notification({
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
    ended = backend._convert_notification({
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
                "agentsStates": {
                    "child-1": {"status": "completed", "message": "Found the schema"},
                },
                "status": "completed",
            },
        },
    })

    assert ended[0].type == "subagent_end"
    assert ended[0].metadata["description"] == "Research the API"
    assert ended[0].metadata["summary"] == "Found the schema"
    assert "Found the schema" in ended[0].content


def test_image_and_review_items_have_frontend_friendly_payloads():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    viewed = backend._item_started({
        "id": "image-1",
        "type": "imageView",
        "path": "/tmp/chart.png",
    })
    generated = backend._item_completed({
        "id": "image-2",
        "type": "imageGeneration",
        "status": "completed",
        "result": "generated",
        "savedPath": "/tmp/generated.png",
    })
    review = backend._item_completed({
        "id": "review-1",
        "type": "enteredReviewMode",
        "review": "Review the current diff",
    })

    assert json.loads(viewed[0].content.split(": ", 1)[1])["file_path"] == "/tmp/chart.png"
    assert json.loads(generated[-1].content)["saved_path"] == "/tmp/generated.png"
    assert review[0].type == "review"


def test_is_alive_tracks_codex_process_state():
    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    assert backend.is_alive is False

    backend._proc = SimpleNamespace(returncode=None)
    assert backend.is_alive is True

    backend._proc.returncode = 0
    assert backend.is_alive is False
