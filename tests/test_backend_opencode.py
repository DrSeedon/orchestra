"""Task #96/#97 — OpenCodeBackend: event mapping, turn_end parity, MCP translation,
and the poll-based turn-completion loop (#97).

Pure-logic unit tests over fixtures captured from a live opencode v1.17.6 daemon.
No daemon needed — the events() loop is exercised with a fake SSE stream + a fake
status sequence; the lifecycle is covered by the gated integration test at the bottom
(skipped if the binary is absent).
"""

import contextlib
import shutil

import httpx
import pytest

from app.backend_opencode import (
    OpenCodeBackend, _to_opencode_mcp, _free_port, DEFAULT_CONTEXT,
)


def _b(model="claude-sonnet-5[1m]"):
    return OpenCodeBackend(model=model, cwd="/tmp")


# ── provider/model split ──

def test_model_split_from_prefixed():
    b = OpenCodeBackend(model="anthropic/claude-sonnet-5[1m]", cwd="/tmp")
    assert b.provider_id == "anthropic"
    assert b.model == "claude-sonnet-5[1m]"


def test_model_bare_keeps_default_provider():
    b = OpenCodeBackend(model="mimo-v2.5-free", cwd="/tmp", provider_id="opencode")
    assert b.provider_id == "opencode"
    assert b.model == "mimo-v2.5-free"
    assert b._transport_provider_id == "opencode"
    assert b._transport_model_id == "mimo-v2.5-free"


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
    b = _b("claude-sonnet-5[1m]")
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


def test_turn_end_uses_registry_context_limit():
    b = OpenCodeBackend(model="x-ai/grok-4", cwd="/tmp", context_limit=256_000)
    msg = {"info": {"cost": 0, "finish": "stop", "error": None,
                    "tokens": {"input": 128_000}}}
    event = b._turn_end(msg)
    assert event.metadata["context_pct"] == 50
    assert event.metadata["max_tokens"] == 256_000


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


# ── secure inline config ──

def test_inline_config_keeps_secret_out_of_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.test")
    b = OpenCodeBackend(model="claude-sonnet-5[1m]", cwd=str(tmp_path),
                        mcp_servers={"orchestra": {"command": "py", "args": ["s.py"], "env": {}}})
    import json
    cfg = json.loads(b._build_inline_config())
    assert cfg["mcp"]["orchestra"]["type"] == "local"
    assert cfg["permission"] == {"edit": "allow", "bash": "allow", "webfetch": "allow",
                                 "external_directory": "allow", "doom_loop": "allow"}
    assert cfg["provider"]["openrouter"]["options"]["apiKey"] == "{env:ANTHROPIC_API_KEY}"
    assert cfg["provider"]["openrouter"]["options"]["baseURL"] == "https://proxy.test/v1"
    assert not (tmp_path / "opencode.json").exists()


def test_daemon_env_uses_inline_config_without_embedding_key(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    b = OpenCodeBackend(model="x-ai/grok-4", cwd=str(tmp_path))
    env = b._build_daemon_env()
    assert "sk-secret" not in env["OPENCODE_CONFIG_CONTENT"]
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["model"] == "openrouter/x-ai/grok-4"


def test_native_opencode_model_keeps_native_transport():
    import json
    b = OpenCodeBackend(model="opencode/mimo-v2.5-free", cwd="/tmp")
    assert json.loads(b._build_inline_config())["model"] == "opencode/mimo-v2.5-free"


@pytest.mark.asyncio
async def test_wait_ready_retries_read_timeout(monkeypatch):
    class _Probe:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _path):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("daemon is still starting")
            return type("_Response", (), {"status_code": 200})()

    async def _no_sleep(_seconds):
        return None

    probe = _Probe()
    monkeypatch.setattr("app.backend_opencode.httpx.AsyncClient", lambda **_kwargs: probe)
    monkeypatch.setattr("app.backend_opencode.asyncio.sleep", _no_sleep)

    assert await _b()._wait_ready() is True
    assert probe.calls == 2


# ── poll-based events() loop (#97 — fake SSE + scripted status, no daemon) ──

import asyncio
import json as _json


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHTTP:
    """Minimal stand-in for httpx.AsyncClient: answers GET /session/status from a
    scripted sequence and GET /session/{id}/message with a fixed assistant message.

    status_seq items, consumed one per /session/status call (last value repeats):
      "idle"|"busy"|"retry"  → {sid: {"type": v}} (or {} for idle),
      None                    → raise (connection error),
      dict                    → returned verbatim as the json body.
    """
    def __init__(self, status_seq, sid="ses_x", message=None, message_exc=None):
        self._status_seq = list(status_seq)
        self._i = 0
        self._sid = sid
        self._message = message if message is not None else [
            {"info": {"role": "assistant", "cost": 0.5, "finish": "stop", "error": None,
                      "tokens": {"input": 10, "output": 2}}}]
        self._message_exc = message_exc
        self.status_calls = 0

    async def get(self, url, **kw):
        if url == "/session/status":
            self.status_calls += 1
            v = self._status_seq[min(self._i, len(self._status_seq) - 1)]
            self._i += 1
            if v is None:
                raise RuntimeError("status connect error")
            if isinstance(v, dict):
                return _FakeResp(200, v)
            body = {} if v == "idle" else {self._sid: {"type": v}}
            return _FakeResp(200, body)
        if url.endswith("/message"):
            if self._message_exc:
                raise self._message_exc
            return _FakeResp(200, self._message)
        raise AssertionError(f"unexpected GET {url}")


def _poll_backend(sse_lines, status_seq, message=None, message_exc=None, session_id="ses_x"):
    """Wire a backend with a fake SSE stream and a scripted /session/status sequence.
    Marks the turn active so events() proceeds past its send()-wait."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = session_id
    b._http = _FakeHTTP(status_seq, sid=session_id, message=message, message_exc=message_exc)  # type: ignore
    b._turn_active = True
    b._sse_response = object()  # truthy guard; _sse_lines is patched so it's never read

    async def fake_sse():
        for ln in sse_lines:
            yield _json.dumps(ln) if isinstance(ln, dict) else ln

    b._sse_lines = fake_sse  # type: ignore
    return b


async def _drain(b):
    return [e async for e in b.events()]


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Shrink the 3s status-poll interval so multi-poll tests don't wall-clock out."""
    import app.backend_opencode as bo
    monkeypatch.setattr(bo, "STATUS_POLL_INTERVAL", 0.01)


@pytest.mark.asyncio
async def test_events_status_idle_yields_one_turn_end():
    """Happy path: SSE part streams, status flips busy→idle → exactly one turn_end."""
    b = _poll_backend(
        [{"type": "message.part.updated", "properties": {"sessionID": "ses_x",
            "part": {"type": "text", "text": "hi", "id": "p"}}}],
        status_seq=["busy", "idle"],
        message=[{"info": {"role": "assistant", "cost": 0.5, "finish": "stop",
                           "error": None, "tokens": {"input": 10, "output": 2}}}])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert [e.type for e in out] == ["text", "turn_end"]
    assert out[-1].metadata["cost_usd"] == 0.5
    assert out[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_events_ends_when_sse_never_sends_idle():
    """THE BUG: SSE only sends a heartbeat (no sessionID, no session.idle), but status
    polling reports idle → turn still ends. Previously stranded RUNNING forever."""
    b = _poll_backend(
        [{"type": "server.heartbeat", "properties": {}}],  # global, no sessionID
        status_seq=["busy", "idle"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_events_filters_other_sessions():
    b = _poll_backend(
        [{"type": "message.part.updated", "properties": {"sessionID": "OTHER",
            "part": {"type": "text", "text": "leak", "id": "p"}}}],
        status_seq=["busy", "idle"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert [e.type for e in out] == ["turn_end"]  # foreign event dropped


@pytest.mark.asyncio
async def test_events_idle_from_submit_waits_for_grace():
    """status idle from the very first poll with NO activity → must NOT end immediately;
    ends only after SUBMIT_GRACE (patched small)."""
    import app.backend_opencode as bo
    b = _poll_backend([], status_seq=["idle", "idle", "idle"])
    orig = bo.SUBMIT_GRACE
    bo.SUBMIT_GRACE = 0.01  # tiny grace so the test is fast
    try:
        out = await asyncio.wait_for(_drain(b), timeout=5)
    finally:
        bo.SUBMIT_GRACE = orig
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_events_retry_state_not_premature_end():
    """type=='retry' means daemon is auto-retrying → treat as busy, never end."""
    b = _poll_backend([], status_seq=["retry", "retry", "idle"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is True
    assert b._http.status_calls >= 3  # polled through both retries before ending


@pytest.mark.asyncio
async def test_events_single_status_failure_does_not_end():
    """One transient status-poll failure must NOT end the turn (codex #5)."""
    b = _poll_backend([], status_seq=[None, "busy", "idle"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is True  # recovered after the single failure


@pytest.mark.asyncio
async def test_events_repeated_status_failures_error_end():
    """STATUS_FAIL_THRESHOLD consecutive failures → error turn_end, no hang."""
    b = _poll_backend([], status_seq=[None, None, None, None])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert out[-1].metadata["stop_reason"] == "status_poll_failed"


@pytest.mark.asyncio
async def test_events_session_error_ends_turn():
    b = _poll_backend(
        [{"type": "session.error", "properties": {"sessionID": "ses_x",
            "error": {"name": "X"}}}],
        status_seq=["busy", "busy"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    types = [e.type for e in out]
    assert types[0] == "error"
    assert types[-1] == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert out[-1].metadata["stop_reason"] == "session_error"


@pytest.mark.asyncio
async def test_events_sse_read_exception():
    """SSE raises a non-StopAsyncIteration error → error + turn_end, no crash escaping."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = _FakeHTTP(["busy"])  # type: ignore
    b._turn_active = True
    b._sse_response = object()  # type: ignore

    async def boom_sse():
        raise RuntimeError("ReadError")
        yield  # pragma: no cover
    b._sse_lines = boom_sse  # type: ignore

    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert "sse_failed" in out[-1].metadata["stop_reason"]


@pytest.mark.asyncio
async def test_events_malformed_event_no_keyerror():
    """Event without properties/type must not raise KeyError."""
    b = _poll_backend(
        [{"weird": "no type or properties"}],
        status_seq=["busy", "idle"])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"


@pytest.mark.asyncio
async def test_events_message_fetch_empty_error_end():
    """status idle but message API returns [] → exactly one error turn_end (codex #3)."""
    import app.backend_opencode as bo
    b = _poll_backend([], status_seq=["busy", "idle"], message=[])
    orig = bo.SUBMIT_GRACE
    bo.SUBMIT_GRACE = 0.01
    try:
        out = await asyncio.wait_for(_drain(b), timeout=5)
    finally:
        bo.SUBMIT_GRACE = orig
    assert len(out) == 1
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["stop_reason"] == "no_assistant_message"


@pytest.mark.asyncio
async def test_events_message_fetch_raises_error_end():
    """message API raises → exactly one error turn_end, no escape (codex #3)."""
    b = _poll_backend([], status_seq=["busy", "idle"],
                      message_exc=RuntimeError("500 boom"))
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is False
    assert "message_fetch_failed" in out[-1].metadata["stop_reason"]


@pytest.mark.asyncio
async def test_events_flat_assistant_message_shape():
    """message endpoint may return a FLAT AssistantMessage (no 'info' wrapper) →
    turn_end must still extract non-zero cost/tokens (codex #7)."""
    b = _poll_backend([], status_seq=["busy", "idle"],
                      message=[{"role": "assistant", "cost": 0.9, "finish": "stop",
                                "error": None, "tokens": {"input": 5, "output": 1}}])
    out = await asyncio.wait_for(_drain(b), timeout=5)
    assert out[-1].metadata["cost_usd"] == 0.9
    assert out[-1].metadata["input_tokens"] == 5


@pytest.mark.asyncio
async def test_events_long_busy_turn_has_no_absolute_wall_clock_deadline(monkeypatch):
    """A healthy busy turn may outlive an arbitrary wall-clock threshold."""
    import app.backend_opencode as bo
    monkeypatch.setattr(bo, "STATUS_POLL_INTERVAL", 0.01)
    b = _poll_backend(
        [],
        status_seq=["busy"] * 8 + ["idle"],
        message=[{"role": "assistant", "cost": 0, "finish": "stop",
                  "error": None, "tokens": {}}],
    )
    out = await asyncio.wait_for(_drain(b), timeout=2)
    assert out[-1].type == "turn_end"
    assert out[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_send_rejects_overlapping_turn():
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = object()  # type: ignore
    b._turn_active = True
    with pytest.raises(RuntimeError, match="already in progress"):
        await b.send("x")


@pytest.mark.asyncio
async def test_events_cancel_resets_turn_active():
    """Generator cancelled mid-events() → _turn_active reset so the next send() works
    (codex #4)."""
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = _FakeHTTP(["busy", "busy", "busy"])  # type: ignore
    b._turn_active = True
    b._sse_response = object()  # type: ignore

    async def hang_sse():
        await asyncio.sleep(30)
        yield  # pragma: no cover
    b._sse_lines = hang_sse  # type: ignore

    agen = b.events()
    task = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await agen.aclose()
    assert b._turn_active is False   # finally block cleared it
    assert b._sse_response is None


@pytest.mark.asyncio
async def test_disconnect_clears_turn_active():
    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._turn_active = True
    await b.disconnect()
    assert b._turn_active is False


@pytest.mark.asyncio
async def test_send_posts_prompt_async_with_nested_model():
    """send() must POST /prompt_async with NESTED model:{providerID,modelID} (the schema
    differs from the old /message). Guards against silent daemon-API drift."""
    captured = {}

    class _CapHTTP:
        def build_request(self, method, url):
            return ("req", method, url)

        async def send(self, req, stream=False):
            return object()  # fake SSE response

        async def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json
            return _FakeResp(204, None)

    b = OpenCodeBackend(model="anthropic/claude-sonnet-5[1m]", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = _CapHTTP()  # type: ignore
    b.system_prompt = "sys"
    await b.send("hello")
    assert captured["url"] == "/session/ses_x/prompt_async"
    assert captured["body"]["model"] == {
        "providerID": "openrouter",
        "modelID": "anthropic/claude-sonnet-5[1m]",
    }
    assert captured["body"]["parts"] == [{"type": "text", "text": "hello"}]
    assert captured["body"]["system"] == "sys"
    assert b._turn_active is True


@pytest.mark.asyncio
async def test_send_failure_clears_turn_active():
    """A failed prompt_async must not leave _turn_active / SSE half-open set."""
    class _BoomHTTP:
        def build_request(self, method, url):
            return ("req", method, url)

        async def send(self, req, stream=False):
            return object()

        async def post(self, url, json=None):
            return _FakeResp(500, None)  # raise_for_status → RuntimeError

    b = OpenCodeBackend(model="m", cwd="/tmp")
    b._session_id = "ses_x"
    b._http = _BoomHTTP()  # type: ignore
    with pytest.raises(RuntimeError):
        await b.send("x")
    assert b._turn_active is False
    assert b._sse_response is None


# ── gated integration (real daemon) ──

@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode binary not installed")
@pytest.mark.asyncio
async def test_integration_lifecycle(tmp_path, monkeypatch):
    """Real daemon: connect creates a session + spawns the daemon; disconnect reaps it.
    Does NOT drive a model turn (the free model is slow/rate-limited and would flake)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    b = OpenCodeBackend(model="opencode/mimo-v2.5-free", cwd=str(tmp_path))
    try:
        await b.connect()
        assert b.session_id and b.session_id.startswith("ses_")
        assert b._proc is not None and b._proc.returncode is None  # daemon running
        assert not (tmp_path / "opencode.json").exists()           # no secret-bearing file
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
