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
    GrokMcpIsolationError,
    GROK_CONTEXT_LIMITS,
    GROK_COST_TICK_USD,
    GROK_TOKEN_PRICES,
    _grok_cost,
    ensure_grok_home,
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
    # Configured with orchestra, so a healthy orchestra is silent — an unconfigured server
    # reaching `ready` is a different case and is covered by the isolation tests below.
    b = _backend(mcp_servers={"orchestra": {"command": "x"}})
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


# ── MCP isolation (T2) ──
#
# Grok merges servers it discovers itself into every session — passing only `orchestra`
# still started the user's websearch/pandoc servers and broadcast their env, which is how a
# live OPENROUTER_API_KEY reached a task artifact. Measured, not assumed:
#   - session/new.mcpServers MERGES with discovery, it does not replace it
#   - `[compat.claude] mcps = false` suppresses it, but only from the USER config;
#     the same key in a project .grok/config.toml is ignored
# Hence an Orchestra-owned GROK_HOME plus a check on what actually came up.

def test_expected_servers_seeded_from_our_config_only():
    b = _backend(mcp_servers={"orchestra": {"command": "x"}})
    assert b._expected_servers == {"orchestra"}


def test_isolation_passes_when_only_expected_servers_start():
    async def scenario():
        b = _backend(mcp_servers={"orchestra": {"command": "x"}})
        b._mcp_ready = asyncio.Event()
        b._mcp_ready.set()
        b._started_servers = {"orchestra"}
        await b._verify_mcp_isolation()
    asyncio.run(scenario())


def test_isolation_refuses_connect_on_foreign_server():
    """A worker with foreign tools — and foreign secrets in their env — must not start."""
    async def scenario():
        b = _backend(mcp_servers={"orchestra": {"command": "x"}})
        b._mcp_ready = asyncio.Event()
        b._mcp_ready.set()
        b._started_servers = {"orchestra", "websearch"}
        await b._verify_mcp_isolation()
    with pytest.raises(GrokMcpIsolationError, match="websearch"):
        asyncio.run(scenario())


def test_roster_tracked_from_servers_updated_not_only_status():
    """servers_updated lands before mcp_initialized; server_status can arrive mid-turn.

    Tracking only server_status made the connect-time check pass vacuously.
    """
    b = _backend(mcp_servers={"orchestra": {"command": "x"}})
    b._track_mcp({"method": "_x.ai/mcp/servers_updated", "params": {"mcpServers": [
        {"name": "websearch", "env": [{"name": "OPENROUTER_API_KEY", "value": "sk-leak"}]},
    ]}})
    assert b._started_servers == {"websearch"}


def test_roster_ignores_servers_that_never_became_ready():
    b = _backend(mcp_servers={"orchestra": {"command": "x"}})
    b._track_mcp({"method": "_x.ai/mcp/server_status",
                  "params": {"name": "broken", "status": "unavailable"}})
    assert b._started_servers == set()


def test_mcp_initialized_sets_ready_gate():
    b = _backend()
    b._mcp_ready = asyncio.Event()
    b._track_mcp({"method": "_x.ai/mcp_initialized", "params": {"mcpToolCount": 35}})
    assert b._mcp_ready.is_set()


def test_unexpected_ready_server_surfaces_as_error_mid_session():
    b = _backend(mcp_servers={"orchestra": {"command": "x"}})
    (event,) = b._convert({"method": "_x.ai/mcp/server_status",
                           "params": {"name": "websearch", "status": "ready"}})
    assert event.type == "error"
    assert "isolation breach" in event.content
    assert b._convert({"method": "_x.ai/mcp/server_status",
                       "params": {"name": "orchestra", "status": "ready"}}) == []


def test_grok_home_is_isolated_and_disables_claude_compat_mcp(tmp_path, monkeypatch):
    home = tmp_path / "grok-home"
    fake_user_home = tmp_path / "user-grok"
    fake_user_home.mkdir()
    (fake_user_home / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("app.backend_grok.GROK_HOME_DIR", home)
    monkeypatch.setattr("app.backend_grok.GROK_USER_HOME", fake_user_home)

    result = ensure_grok_home()
    assert result == home
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert "[compat.claude]" in config and "mcps = false" in config
    # Credentials are shared by symlink so a token refresh does not rot in a private copy.
    assert (home / "auth.json").is_symlink()
    assert (home / "auth.json").readlink() == fake_user_home / "auth.json"
    # Idempotent: a second connect must not fail or duplicate the link.
    ensure_grok_home()
    assert (home / "auth.json").is_symlink()


def test_grok_home_fails_loud_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("app.backend_grok.GROK_HOME_DIR", tmp_path / "h")
    monkeypatch.setattr("app.backend_grok.GROK_USER_HOME", tmp_path / "missing")
    with pytest.raises(RuntimeError, match="grok login"):
        ensure_grok_home()


def test_build_env_forces_orchestra_grok_home(tmp_path, monkeypatch):
    home = tmp_path / "grok-home"
    fake_user_home = tmp_path / "user-grok"
    fake_user_home.mkdir()
    (fake_user_home / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("app.backend_grok.GROK_HOME_DIR", home)
    monkeypatch.setattr("app.backend_grok.GROK_USER_HOME", fake_user_home)
    # An inherited GROK_HOME must not defeat isolation.
    monkeypatch.setenv("GROK_HOME", "/somewhere/else")
    assert _backend()._build_env()["GROK_HOME"] == str(home)


# ── session resume (T3) ──
#
# Measured against the live CLI: the session store is keyed by (cwd, sessionId).
# Resume SURVIVES a branch switch inside the same worktree (main -> feature/x kept the id
# and the recalled content), but rejects a different cwd with "Path not found". Two workers
# sharing one GROK_HOME got distinct ids and did not cross-talk.

def test_sandbox_config_write_is_atomic(tmp_path):
    """A shared home means overlapping connects.

    A plain write truncates first, and a worker starting in that window reads an empty
    config — no `mcps = false`, isolation silently off. Measured before the fix: 57.9% of
    concurrent reads saw an empty file; after: 0%.
    """
    import threading
    import app.backend_grok as module

    config = tmp_path / "config.toml"
    module._write_sandbox_config(config)
    seen: list[str] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                seen.append(config.read_text(encoding="utf-8"))
            except OSError:
                seen.append("<enoent>")

    def writer():
        for _ in range(300):
            config.write_text("", encoding="utf-8")  # force a rewrite each round
            module._write_sandbox_config(config)

    t = threading.Thread(target=reader)
    t.start()
    try:
        writer()
    finally:
        stop.set()
        t.join()
    # Readers may observe the old content or the new one, never a torn/empty file.
    assert seen, "reader never sampled the file"
    assert all(text in ("", module._GROK_SANDBOX_CONFIG) for text in seen)
    assert any(text == module._GROK_SANDBOX_CONFIG for text in seen)


def test_sandbox_config_rewritten_when_content_drifts(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[compat.claude]\nmcps = true\n", encoding="utf-8")
    import app.backend_grok as module
    module._write_sandbox_config(config)
    assert config.read_text(encoding="utf-8") == module._GROK_SANDBOX_CONFIG
    assert not list(tmp_path.glob(".config.toml.*.tmp"))  # no temp files left behind


def test_resume_failure_warning_is_not_filtered_by_session_routing():
    """events() drops notifications for a different sessionId.

    The resume warning is about the OLD id, so carrying it under `sessionId` made the
    message announcing the lost history get filtered out — silently.
    """
    b = _backend()
    b._session_id = "new-id"
    (warning,) = b._convert({"method": "_session/resume_failed", "params": {
        "staleSessionId": "old-id", "message": "Path not found."}})
    assert warning.type == "warning"
    assert "old-id" in warning.content
    assert "not available" in warning.content


def test_connect_refuses_missing_worktree():
    """A removed worktree otherwise surfaces as a bare FileNotFoundError from spawn."""
    async def scenario():
        await _backend(cwd="/tmp/definitely-not-here-95").connect()
    with pytest.raises(RuntimeError, match="worktree removed or relocated"):
        asyncio.run(scenario())


def test_session_id_exposed_for_persistence():
    b = _backend(resume_session_id="019f-abc")
    assert b.session_id == "019f-abc"


def test_explicit_grok_bin_env_beats_path_autodiscovery(monkeypatch):
    """A stray `grok` in PATH must not win over deliberate configuration."""
    import importlib
    monkeypatch.setenv("GROK_BIN", "/opt/pinned/grok")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/grok")
    module = importlib.reload(importlib.import_module("app.backend_grok"))
    try:
        assert module.GROK_BIN == "/opt/pinned/grok"
    finally:
        monkeypatch.undo()
        importlib.reload(module)


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
