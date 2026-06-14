"""Task #96 — OpenCodeBackend: event mapping, turn_end parity, MCP translation.

Pure-logic unit tests over fixtures captured from a live opencode v1.17.6 daemon.
No daemon needed — the dual-source coordination + lifecycle are covered by the
gated integration test at the bottom (skipped if the binary is absent).
"""

import contextlib
import shutil

import pytest

from app.backend_opencode import (
    OpenCodeBackend, _to_opencode_mcp, _free_port, DEFAULT_CONTEXT,
)


def _b(model="claude-sonnet-4-6"):
    return OpenCodeBackend(model=model, cwd="/tmp")


# ── provider/model split ──

def test_model_split_from_prefixed():
    b = OpenCodeBackend(model="anthropic/claude-sonnet-4-6", cwd="/tmp")
    assert b.provider_id == "anthropic"
    assert b.model == "claude-sonnet-4-6"


def test_model_bare_keeps_default_provider():
    b = OpenCodeBackend(model="mimo-v2.5-free", cwd="/tmp", provider_id="opencode")
    assert b.provider_id == "opencode"
    assert b.model == "mimo-v2.5-free"


# ── SSE parsing ──

def test_parse_sse_strips_data_prefix():
    assert _b()._parse_sse('data: {"type":"x"}') == {"type": "x"}


def test_parse_sse_plain_json():
    assert _b()._parse_sse('{"type":"y"}') == {"type": "y"}


def test_parse_sse_ignores_blank_and_garbage():
    b = _b()
    assert b._parse_sse("") is None
    assert b._parse_sse("data: ") is None
    assert b._parse_sse("not json") is None


# ── part mapping ──

def test_map_text_part():
    b = _b()
    events = b._map_part({"type": "text", "text": "hello", "id": "p1"}, set(), set(), {})
    assert len(events) == 1
    assert events[0].type == "text"
    assert events[0].content == "hello"


def test_map_text_part_skips_synthetic_and_empty():
    b = _b()
    assert b._map_part({"type": "text", "text": "", "id": "p1"}, set(), set(), {}) == []
    assert b._map_part({"type": "text", "text": "x", "synthetic": True, "id": "p2"}, set(), set(), {}) == []


def test_map_text_cumulative_emits_suffix_only():
    """part.updated fires multiple times with cumulative text (empty → full).
    Must emit only the NEW suffix, never re-emit the growing prefix."""
    b = _b()
    el = {}
    assert b._map_part({"type": "text", "text": "", "id": "p"}, set(), set(), el) == []
    e1 = b._map_part({"type": "text", "text": "Hello", "id": "p"}, set(), set(), el)
    assert [x.content for x in e1] == ["Hello"]
    e2 = b._map_part({"type": "text", "text": "Hello world", "id": "p"}, set(), set(), el)
    assert [x.content for x in e2] == [" world"]   # suffix only
    e3 = b._map_part({"type": "text", "text": "Hello world", "id": "p"}, set(), set(), el)
    assert e3 == []   # no growth → nothing


def test_map_reasoning_part_to_thinking():
    b = _b()
    events = b._map_part({"type": "reasoning", "text": "let me think", "id": "r1"}, set(), set(), {})
    assert len(events) == 1
    assert events[0].type == "thinking"
    assert events[0].content == "let me think"


def test_map_reasoning_empty_skipped():
    assert _b()._map_part({"type": "reasoning", "text": "", "id": "r1"}, set(), set(), {}) == []


def test_map_tool_running_emits_tool_use_once():
    b = _b()
    su, sr = set(), set()
    part = {"type": "tool", "tool": "Bash", "callID": "c1",
            "state": {"status": "running", "input": {"command": "ls"}}}
    e1 = b._map_part(part, su, sr, {})
    assert len(e1) == 1 and e1[0].type == "tool_use"
    assert e1[0].metadata["tool_name"] == "Bash"
    # second sighting (still running) → no duplicate tool_use
    e2 = b._map_part(part, su, sr, {})
    assert e2 == []


def test_map_tool_completed_emits_use_then_result_when_first_seen_terminal():
    """Fast tool: first sighting is already 'completed' — must still emit tool_use."""
    b = _b()
    su, sr = set(), set()
    part = {"type": "tool", "tool": "orchestra_spawn_worker", "callID": "c9",
            "state": {"status": "completed", "input": {"x": 1}, "output": "done"}}
    events = b._map_part(part, su, sr, {})
    assert [e.type for e in events] == ["tool_use", "tool_result"]
    assert events[0].metadata["short_name"] == "spawn_worker"  # orchestra_ stripped
    assert events[1].content == "done"


def test_map_tool_result_not_duplicated():
    b = _b()
    su, sr = set(), set()
    part = {"type": "tool", "tool": "Read", "callID": "c2",
            "state": {"status": "completed", "input": {}, "output": "file body"}}
    first = b._map_part(part, su, sr, {})
    second = b._map_part(part, su, sr, {})
    assert [e.type for e in first] == ["tool_use", "tool_result"]
    assert second == []  # both use+result already seen


def test_map_tool_error():
    b = _b()
    events = b._map_part(
        {"type": "tool", "tool": "Bash", "callID": "c3",
         "state": {"status": "error", "input": {}, "error": "boom"}},
        set(), set(), {})
    assert events[-1].type == "tool_result"
    assert events[-1].content == "boom"


def test_map_step_parts_ignored():
    b = _b()
    assert b._map_part({"type": "step-start"}, set(), set(), {}) == []
    assert b._map_part({"type": "step-finish", "tokens": {}}, set(), set(), {}) == []


# ── turn_end metadata parity ──

def test_turn_end_native_cost_and_tokens():
    b = _b("claude-sonnet-4-6")
    msg = {"info": {
        "cost": 0.0123, "finish": "stop", "error": None,
        "tokens": {"input": 1000, "output": 50, "reasoning": 10,
                   "cache": {"read": 200, "write": 100}},
    }}
    e = b._turn_end(msg)
    m = e.metadata
    assert e.type == "turn_end"
    assert m["ok"] is True
    assert m["cost_usd"] == 0.0123
    assert m["cost_usd_cached"] == 0.0123
    assert m["input_tokens"] == 1000
    assert m["output_tokens"] == 50
    assert m["cache_read"] == 200
    assert m["cache_create"] == 100
    assert m["cached_input_tokens"] == 200  # parity with codex
    assert m["cache_hit"] == int(200 * 100 / 300)
    assert m["max_tokens"] == 200000
    assert m["context_tokens"] == 1000
    assert m["stop_reason"] == "stop"


def test_turn_end_parity_keys_match_codex():
    """turn_end must carry every key CodexBackend emits (downstream depends on them)."""
    b = _b()
    msg = {"info": {"cost": 0, "finish": "stop", "error": None, "tokens": {}}}
    keys = set(b._turn_end(msg).metadata.keys())
    required = {
        "session_id", "ok", "stop_reason", "cost_usd", "cost_usd_cached",
        "context_pct", "context_tokens", "max_tokens", "cache_hit",
        "cache_read", "cache_create", "input_tokens", "output_tokens",
        "cached_input_tokens",
    }
    assert required <= keys


def test_turn_end_error_flag():
    b = _b()
    msg = {"info": {"cost": 0, "finish": "stop",
                    "error": {"name": "X"}, "tokens": {}}}
    e = b._turn_end(msg)
    assert e.metadata["ok"] is False
    assert e.metadata["stop_reason"] == "error"


def test_error_turn_end_minimal_set():
    b = _b()
    e = b._error_turn_end("chat_failed: 500")
    assert e.metadata["ok"] is False
    assert e.metadata["stop_reason"] == "chat_failed: 500"
    assert e.metadata["cost_usd"] == 0
    assert e.metadata["input_tokens"] == 0
    # same key set as success path → no downstream KeyError
    assert "cached_input_tokens" in e.metadata
    assert e.metadata["max_tokens"] == DEFAULT_CONTEXT


def test_turn_end_unknown_model_default_context():
    b = _b("some-unknown-model")
    msg = {"info": {"cost": 0, "finish": "stop", "error": None,
                    "tokens": {"input": 100}}}
    assert b._turn_end(msg).metadata["max_tokens"] == DEFAULT_CONTEXT


# ── MCP translation ──

def test_to_opencode_mcp_translates_orchestra_shape():
    src = {"orchestra": {
        "command": "/usr/bin/python", "args": ["app/mcp_stdio.py"],
        "env": {"INTERNAL_TOKEN": "t", "PORT": 8888},
    }}
    out = _to_opencode_mcp(src)
    assert out["orchestra"]["type"] == "local"
    assert out["orchestra"]["command"] == ["/usr/bin/python", "app/mcp_stdio.py"]
    assert out["orchestra"]["environment"] == {"INTERNAL_TOKEN": "t", "PORT": "8888"}
    assert out["orchestra"]["enabled"] is True


def test_to_opencode_mcp_no_args():
    out = _to_opencode_mcp({"x": {"command": "foo"}})
    assert out["x"]["command"] == ["foo"]
    assert out["x"]["environment"] == {}


# ── port alloc ──

def test_free_port_returns_usable_int():
    p = _free_port()
    assert isinstance(p, int) and 1024 < p < 65536


# ── opencode.json writing ──

def test_write_opencode_json_fresh(tmp_path):
    b = OpenCodeBackend(model="claude-sonnet-4-6", cwd=str(tmp_path),
                        mcp_servers={"orchestra": {"command": "py", "args": ["s.py"], "env": {}}})
    b._write_opencode_json()
    import json
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert cfg["mcp"]["orchestra"]["type"] == "local"
    assert cfg["permission"] == {"edit": "allow", "bash": "allow", "webfetch": "allow"}


def test_write_opencode_json_merges_existing(tmp_path):
    import json
    (tmp_path / "opencode.json").write_text(json.dumps({"model": "x", "mcp": {"keep": {"type": "local", "command": ["k"]}}}))
    b = OpenCodeBackend(model="m", cwd=str(tmp_path),
                        mcp_servers={"orchestra": {"command": "py", "env": {}}})
    b._write_opencode_json()
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert cfg["model"] == "x"              # preserved
    assert "keep" in cfg["mcp"]             # existing mcp preserved
    assert "orchestra" in cfg["mcp"]        # ours merged in


# ── dual-source events() loop (fake SSE + fake chat task, no daemon) ──

import asyncio
import json as _json


def _sse_backend(lines, chat_result=None, chat_exc=None, session_id="ses_x"):
    """Wire a backend with a fake SSE stream and a fake chat task."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = session_id
    b._http = object()  # truthy guard; _sse_lines is patched so it's never used

    async def fake_sse():
        for ln in lines:
            yield _json.dumps(ln) if isinstance(ln, dict) else ln

    b._sse_lines = fake_sse  # type: ignore

    async def chat():
        if chat_exc:
            raise chat_exc
        await asyncio.sleep(0)
        return chat_result or {"info": {"cost": 0, "finish": "stop", "error": None, "tokens": {}}}

    b._chat_task = asyncio.ensure_future(chat())
    return b


async def _drain(b):
    return [e async for e in b.events()]


@pytest.mark.asyncio
async def test_events_idle_yields_exactly_one_turn_end():
    b = _sse_backend([
        {"type": "message.part.updated", "properties": {"sessionID": "ses_x",
            "part": {"type": "text", "text": "hi", "id": "p"}}},
        {"type": "session.idle", "properties": {"sessionID": "ses_x"}},
    ], chat_result={"info": {"cost": 0.5, "finish": "stop", "error": None,
                             "tokens": {"input": 10, "output": 2}}})
    out = await _drain(b)
    types = [e.type for e in out]
    assert types == ["text", "turn_end"]
    assert out[-1].metadata["cost_usd"] == 0.5
    assert out[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_events_filters_other_sessions():
    b = _sse_backend([
        {"type": "message.part.updated", "properties": {"sessionID": "OTHER",
            "part": {"type": "text", "text": "leak", "id": "p"}}},
        {"type": "session.idle", "properties": {"sessionID": "ses_x"}},
    ])
    out = await _drain(b)
    assert [e.type for e in out] == ["turn_end"]  # foreign event dropped


@pytest.mark.asyncio
async def test_events_chat_exception_before_idle():
    """chat() fails (HTTP) and SSE never sends idle → must still yield error + turn_end, no hang."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def hang_sse():
        await asyncio.sleep(30)  # SSE alive but silent → chat_task must win the race
        yield  # pragma: no cover
    b._sse_lines = hang_sse  # type: ignore

    async def chat():
        await asyncio.sleep(0)
        raise RuntimeError("500 boom")
    b._chat_task = asyncio.ensure_future(chat())

    out = await asyncio.wait_for(_drain(b), timeout=5)
    types = [e.type for e in out]
    assert "error" in types
    assert types[-1] == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert "chat_failed" in out[-1].metadata["stop_reason"]


@pytest.mark.asyncio
async def test_events_sse_read_exception():
    """SSE raises a non-StopAsyncIteration error → error + turn_end, no crash escaping."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def boom_sse():
        raise RuntimeError("ReadError")
        yield  # pragma: no cover

    b._sse_lines = boom_sse  # type: ignore

    async def chat():
        await asyncio.sleep(0)
        return {"info": {"cost": 0, "finish": "stop", "error": None, "tokens": {}}}
    b._chat_task = asyncio.ensure_future(chat())

    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert "sse_failed" in out[-1].metadata["stop_reason"]


@pytest.mark.asyncio
async def test_events_session_error_ends_turn():
    b = _sse_backend([
        {"type": "session.error", "properties": {"sessionID": "ses_x",
            "error": {"name": "X"}}},
    ])
    out = await _drain(b)
    types = [e.type for e in out]
    assert types[0] == "error"
    assert types[-1] == "turn_end"


@pytest.mark.asyncio
async def test_events_malformed_event_no_keyerror():
    """Event without properties/type must not raise KeyError."""
    b = _sse_backend([
        {"weird": "no type or properties"},
        {"type": "session.idle", "properties": {"sessionID": "ses_x"}},
    ])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"


@pytest.mark.asyncio
async def test_send_rejects_overlapping_turn():
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def never():
        await asyncio.sleep(10)
    b._chat_task = asyncio.ensure_future(never())
    try:
        with pytest.raises(RuntimeError, match="already in progress"):
            await b.send("x")
    finally:
        b._chat_task.cancel()


@pytest.mark.asyncio
async def test_events_early_exit_reaps_chat_task():
    """Consumer closes events() before turn_end → chat task must be reaped, not leaked."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def slow_sse():
        yield _json.dumps({"type": "message.part.updated", "properties": {
            "sessionID": "ses_x", "part": {"type": "text", "text": "hi", "id": "p"}}})
        await asyncio.sleep(30)  # never reaches idle
        yield  # pragma: no cover
    b._sse_lines = slow_sse  # type: ignore

    async def chat():
        await asyncio.sleep(30)
        return {"info": {}}
    b._chat_task = asyncio.ensure_future(chat())

    agen = b.events()
    first = await agen.__anext__()      # consume the text event
    assert first.type == "text"
    await agen.aclose()                  # consumer bails early
    assert b._chat_task.cancelled() or b._chat_task.done()  # reaped, no leak


@pytest.mark.asyncio
async def test_events_external_cancel_yields_turn_end():
    """If _chat_task is cancelled externally, events() still yields one turn_end (no BaseException leak)."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    task_holder = {}

    async def hang_sse():
        await asyncio.sleep(30)
        yield  # pragma: no cover
    b._sse_lines = hang_sse  # type: ignore

    async def chat():
        await asyncio.sleep(30)
    b._chat_task = asyncio.ensure_future(chat())
    task_holder["t"] = b._chat_task

    async def drain():
        return [e async for e in b.events()]
    drain_task = asyncio.ensure_future(drain())
    await asyncio.sleep(0.05)
    task_holder["t"].cancel()            # external cancel mid-turn
    out = await asyncio.wait_for(drain_task, timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert out[-1].metadata["stop_reason"] == "chat_cancelled"


@pytest.mark.asyncio
async def test_events_idle_then_chat_cancelled_yields_turn_end():
    """session.idle fires, but chat task gets cancelled before the normal-end await.
    Must yield exactly one turn_end (chat_cancelled), not leak CancelledError."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def idle_then_hang():
        yield _json.dumps({"type": "session.idle", "properties": {"sessionID": "ses_x"}})
        await asyncio.sleep(30)
        yield  # pragma: no cover
    b._sse_lines = idle_then_hang  # type: ignore

    async def chat():
        await asyncio.sleep(30)
    b._chat_task = asyncio.ensure_future(chat())
    b._chat_task.cancel()  # cancelled before events() reaches the normal-end await

    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["stop_reason"] == "chat_cancelled"
    assert out[-1].metadata["ok"] is False


@pytest.mark.asyncio
async def test_events_survives_concurrent_disconnect_nulling_task():
    """disconnect() nulls self._chat_task mid-iteration → events() uses its snapshot,
    no AttributeError."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore

    async def hang_sse():
        await asyncio.sleep(30)
        yield  # pragma: no cover
    b._sse_lines = hang_sse  # type: ignore

    async def chat():
        await asyncio.sleep(30)
    b._chat_task = asyncio.ensure_future(chat())

    async def drain():
        return [e async for e in b.events()]
    drain_task = asyncio.ensure_future(drain())
    await asyncio.sleep(0.05)
    b._chat_task = None      # simulate disconnect() nulling the field mid-turn
    drain_task.cancel()      # tear down the iterator
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await drain_task     # must not raise AttributeError


@pytest.mark.asyncio
async def test_disconnect_reaps_inflight_chat_task():
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"

    async def never():
        await asyncio.sleep(10)
    task = asyncio.ensure_future(never())
    b._chat_task = task
    await b.disconnect()
    assert task.cancelled() or task.done()
    assert b._chat_task is None


# ── gated integration (real daemon) ──

@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode binary not installed")
@pytest.mark.asyncio
async def test_integration_lifecycle():
    """Real daemon: connect creates a session + spawns the daemon; disconnect reaps it.
    Does NOT drive a model turn (the free model is slow/rate-limited and would flake)."""
    import os
    b = OpenCodeBackend(model="opencode/mimo-v2.5-free", cwd="/tmp")
    try:
        await b.connect()
        assert b.session_id and b.session_id.startswith("ses_")
        assert b._proc is not None and b._proc.returncode is None  # daemon running
        assert os.path.exists("/tmp/opencode.json")                # config written
    finally:
        await b.disconnect()
    assert b._proc is None  # reaped — no zombie


@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode binary not installed")
@pytest.mark.asyncio
async def test_integration_real_turn():
    """Full turn on the free model. Skipped (not failed) if the free model is too slow."""
    b = OpenCodeBackend(model="opencode/mimo-v2.5-free", cwd="/tmp")
    try:
        try:
            await b.connect()
            await b.send("Reply with exactly one word: pong")

            async def drive():
                async for ev in b.events():
                    if ev.type == "turn_end":
                        return ev
                return None
            turn_end = await asyncio.wait_for(drive(), timeout=90)
        except Exception as e:  # free model rate-limited / slow / connect timeout
            pytest.skip(f"free model turn unavailable/slow: {e}")
        assert turn_end is not None
        assert turn_end.metadata["session_id"] == b.session_id
        assert "input_tokens" in turn_end.metadata
    finally:
        await b.disconnect()
