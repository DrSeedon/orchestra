"""GrokBackend — event mapping, cost accounting, MCP translation, turn bookkeeping.

Every constant pinned here was measured against the live grok CLI 0.2.112 during task #95
(docs/tasks/95/research.md). The measurements exist because both the secondary sources and
the vendor's own bundled README turned out to be wrong:
  - articles say cached input is $0.50/M; the runtime bills $0.30/M
  - costUsdTicks is 1e-10 USD, not the 1e-9 a first reading assumed
  - the README's "10000-character instruction cap" is not enforced at all
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.backend_grok import (
    GrokBackend,
    GROK_CONTEXT_LIMITS,
    GROK_COST_TICK_USD,
    GROK_TOKEN_PRICES,
    _grok_cost,
)
from app.models import backend_for_model, get_model_spec, resolve_model
from app.runtime_registry import get_runtime


def _backend(**kw):
    kw.setdefault("model", "grok-4.5")
    kw.setdefault("cwd", "/tmp")
    return GrokBackend(**kw)


def _update(kind, **payload):
    update = {"sessionUpdate": kind}
    update.update(payload)
    return {"method": "session/update",
            "params": {"sessionId": None, "update": update, "_meta": {}}}


# ── registry: the silent-misroute trap ──

def test_grok_model_routes_to_grok_runtime():
    # _infer_backend() sends anything that is not gpt-*/claude-* to OpenCode. An
    # unregistered grok-4.5 would therefore run on the wrong runtime with no error at all.
    assert backend_for_model("grok-4.5") == "grok"


def test_grok_aliases_and_provider():
    assert resolve_model("grok") == "grok-4.5"
    spec = get_model_spec("grok-4.5")
    assert spec.runtime == "grok"
    assert spec.provider == "x-ai"
    assert spec.context_length == 500000


def test_unregistered_grok_model_still_infers_grok_runtime():
    assert get_model_spec("grok-9.9-future").runtime == "grok"


def test_proxy_served_grok_stays_on_opencode():
    """`x-ai/grok-4` is the OpenCode daemon's surface, not the Grok CLI's.

    The new `grok-` prefix rule must key on a bare model id; hijacking provider-qualified
    ids would silently move existing proxy models onto a CLI that cannot serve them.
    """
    assert get_model_spec("x-ai/grok-4").runtime == "opencode"


def test_runtime_capabilities_match_measured_behaviour():
    caps = get_runtime("grok").capabilities
    # Measured: a prompt sent during a live turn is queued and runs as its own turn.
    # That is not steering, so mid-turn injection must not be advertised.
    assert caps.mid_turn_inject is False
    assert caps.event_stream == "per_turn"
    assert caps.process_liveness is True


# ── cost: the retracted-unit regression ──

@pytest.mark.parametrize("inp,cached,out,ticks", [
    (22810, 5376, 99, 370748000),
    (23020, 22784, 61, 76732000),
    (73980, 51584, 837, 652892000),
])
def test_cost_formula_matches_runtime_ticks_exactly(inp, cached, out, ticks):
    """Three real turns; the token formula and the runtime's own figure must agree exactly."""
    assert _grok_cost("grok-4.5", inp, cached, out) == pytest.approx(
        ticks * GROK_COST_TICK_USD, abs=1e-12
    )


def test_cost_tick_unit_is_1e_10():
    assert GROK_COST_TICK_USD == 1e-10


def test_cached_rate_is_runtime_value_not_published_value():
    # Published rate cards say $0.50/M cached. Only $0.30 closes the arithmetic on all
    # three measured turns, so the runtime is the source of truth here.
    assert GROK_TOKEN_PRICES["grok-4.5"]["cached"] == 0.30


def test_context_limit_is_runtime_reported():
    assert GROK_CONTEXT_LIMITS["grok-4.5"] == 500000


def test_turn_end_prefers_runtime_cost_over_local_formula():
    b = _backend()
    b._active_prompts = 1
    events = b._finish_prompt("p1", "end_turn", {"usage": {
        "inputTokens": 22810, "cachedReadTokens": 5376,
        "outputTokens": 99, "totalTokens": 22909, "costUsdTicks": 370748000,
    }})
    (end,) = events
    assert end.type == "turn_end"
    assert end.metadata["cost_usd"] == pytest.approx(0.0370748)
    assert end.metadata["input_tokens"] == 22810
    assert end.metadata["cached_input_tokens"] == 5376
    assert end.metadata["context_tokens"] == 22909
    assert end.metadata["max_tokens"] == 500000
    assert end.metadata["ok"] is True


def test_turn_end_falls_back_to_formula_without_ticks():
    b = _backend()
    b._active_prompts = 1
    (end,) = b._finish_prompt("p1", "end_turn", {"usage": {
        "inputTokens": 1000, "cachedReadTokens": 0, "outputTokens": 100,
    }})
    assert end.metadata["cost_usd"] == pytest.approx((1000 * 2.0 + 100 * 6.0) / 1e6)


# ── turn bookkeeping: one turn_end per prompt ──

def test_duplicate_completion_signals_emit_one_turn_end():
    """prompt_complete and the session/prompt result both mark the same turn end."""
    b = _backend()
    b._active_prompts = 1
    first = b._convert({"method": "_x.ai/session/prompt_complete",
                        "params": {"promptId": "p1", "stopReason": "end_turn"}})
    second = b._convert({"method": "_prompt/result",
                         "params": {"stopReason": "end_turn", "_meta": {"promptId": "p1"}}})
    assert [e.type for e in first] == ["turn_end"]
    assert second == []
    assert b._active_prompts == 0


def test_cancelled_turn_is_not_ok():
    b = _backend()
    b._active_prompts = 1
    (end,) = b._finish_prompt("p1", "cancelled", {})
    assert end.metadata["ok"] is False
    assert end.metadata["stop_reason"] == "interrupted"
    assert end.metadata["model_error"] == "interrupted"


def test_failed_prompt_surfaces_error_and_turn_end():
    b = _backend()
    b._active_prompts = 1
    events = b._convert({"method": "_prompt/failed", "params": {"message": "boom"}})
    assert [e.type for e in events] == ["error", "turn_end"]
    assert events[1].metadata["ok"] is False


# ── event mapping (shapes taken from the recorded dump) ──

def test_message_and_thought_chunks_map_to_stream_events():
    b = _backend()
    (msg,) = b._convert(_update("agent_message_chunk",
                                content={"type": "text", "text": "hi"}))
    (thought,) = b._convert(_update("agent_thought_chunk",
                                    content={"type": "text", "text": "hmm"}))
    assert (msg.type, msg.content) == ("stream", "hi")
    assert (thought.type, thought.content) == ("thinking_stream", "hmm")


def test_tool_call_then_update_carries_resolved_mcp_name():
    """Grok routes MCP tools through search_tool/use_tool; the real name arrives later."""
    b = _backend()
    (call,) = b._convert(_update("tool_call", toolCallId="t1", title="use_tool"))
    assert call.type == "tool_use"
    assert call.metadata["tool_use_id"] == "t1"
    (result,) = b._convert(_update("tool_call_update", toolCallId="t1",
                                   title="orchestra__list_agents", status="completed",
                                   content=[{"type": "text", "text": "ok"}]))
    assert result.type == "tool_result"
    assert result.metadata["tool_name"] == "orchestra__list_agents"
    assert result.metadata["is_error"] is False
    assert result.content == "ok"


def test_failed_tool_marks_error():
    b = _backend()
    b._convert(_update("tool_call", toolCallId="t9", title="use_tool"))
    (result,) = b._convert(_update("tool_call_update", toolCallId="t9", status="failed"))
    assert result.metadata["is_error"] is True


def test_in_progress_tool_update_emits_nothing():
    b = _backend()
    assert b._convert(_update("tool_call_update", toolCallId="t1",
                              status="in_progress")) == []


def test_mcp_failure_is_surfaced_as_warning():
    b = _backend()
    (warn,) = b._convert({"method": "_x.ai/mcp/server_status", "params": {
        "name": "orchestra", "status": "unavailable", "detail": "handshake failed"}})
    assert warn.type == "warning"
    assert "orchestra" in warn.content
    assert b._convert({"method": "_x.ai/mcp/server_status",
                       "params": {"name": "orchestra", "status": "ready"}}) == []


def test_process_exit_produces_failed_turn_end():
    b = _backend()
    (end,) = b._convert({"method": "_process/exited",
                         "params": {"returncode": 1, "stderr": "died"}})
    assert end.type == "turn_end"
    assert end.metadata["ok"] is False
    assert end.metadata["model_error"] == "server_error"


def test_queue_depth_tracked_from_queue_events():
    b = _backend()
    b._convert({"method": "_x.ai/queue/changed", "params": {"entries": [{"id": "a"}]}})
    assert b._queue_depth == 1
    b._convert({"method": "_x.ai/queue/changed", "params": {"entries": []}})
    assert b._queue_depth == 0


def test_context_tokens_tracked_from_chunk_meta():
    b = _backend()
    b._convert({"method": "session/update", "params": {
        "update": {"sessionUpdate": "agent_message_chunk",
                   "content": {"type": "text", "text": "x"}},
        "_meta": {"totalTokens": 1234}}})
    assert b._context_tokens == 1234


# ── error classification: no invented quota patterns ──

def test_unknown_error_stays_generic():
    # The terminal quota shape has not been observed yet. Guessing one would make a real
    # limit look like a retryable hiccup.
    assert GrokBackend._classify_error({"message": "something odd"}) == "error"


def test_network_error_classified_as_server_error():
    assert GrokBackend._classify_error(
        {"message": "error sending request"}) == "server_error"


# ── MCP config translation ──

def test_mcp_servers_translate_to_acp_shape_with_env_pairs():
    b = _backend(
        mcp_env={"INTERNAL_TOKEN": "tok"},
        mcp_servers={"orchestra": {
            "command": "/venv/bin/python",
            "args": ["/repo/app/mcp_stdio.py"],
            "env": {"PYTHONPATH": "/repo"},
        }},
    )
    (server,) = b._mcp_server_configs()
    assert server["name"] == "orchestra"
    assert server["type"] == "stdio"
    assert server["command"] == "/venv/bin/python"
    assert server["args"] == ["/repo/app/mcp_stdio.py"]
    # ACP wants a list of {name, value}; passing a dict would start the server unconfigured.
    env = {pair["name"]: pair["value"] for pair in server["env"]}
    assert env == {"INTERNAL_TOKEN": "tok", "PYTHONPATH": "/repo"}


def test_mcp_server_without_command_or_url_is_skipped():
    b = _backend(mcp_servers={"broken": {}})
    assert b._mcp_server_configs() == []


# ── system prompt delivery ──

def test_agent_profile_contains_prompt_and_is_removed_on_cleanup():
    """The ONLY working delivery route — ACP session/new ignores prompt fields silently."""
    b = _backend(system_prompt="ORCHESTRA RULES")
    path = b._write_agent_profile()
    assert path is not None and path.exists()
    body = path.read_text(encoding="utf-8")
    assert "ORCHESTRA RULES" in body
    assert body.startswith("---")
    assert "agents_md: true" in body  # keep project AGENTS.md/CLAUDE.md on top
    b._cleanup_profile()
    assert not path.exists()


def test_no_profile_written_without_system_prompt():
    assert _backend()._write_agent_profile() is None


def test_reasoning_effort_falls_back_to_high():
    assert _backend(reasoning_effort="xhigh").reasoning_effort == "high"
    assert _backend(reasoning_effort="low").reasoning_effort == "low"


# ── events() loop: does not abandon a queued turn ──

def test_events_loop_survives_first_completion_while_queue_pending():
    """A queued prompt runs as its own turn and still needs a listener."""
    async def scenario():
        b = _backend()
        # is_alive reads _proc.returncode — a live process is one that has not exited.
        b._proc = SimpleNamespace(returncode=None)
        b._active_prompts = 2
        b._queue_depth = 1
        for message in (
            {"method": "_x.ai/session/prompt_complete",
             "params": {"promptId": "p1", "stopReason": "end_turn"}},
            {"method": "_x.ai/queue/changed", "params": {"entries": []}},
            {"method": "_x.ai/session/prompt_complete",
             "params": {"promptId": "p2", "stopReason": "end_turn"}},
        ):
            b._notifications.put_nowait(message)
        return [e async for e in b.events()]

    events = asyncio.run(scenario())
    assert [e.type for e in events] == ["turn_end", "turn_end"]
