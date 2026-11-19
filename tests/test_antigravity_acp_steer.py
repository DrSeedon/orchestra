"""Offline contract tests for Wave 7: Antigravity mid-turn steer, mailbox quarantine, provenance, and ACP MCP normalization."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest

from app import acp_tools, backend_antigravity as agy, db, mailbox, runtime_registry
from app.events import InjectedMessage, MessageProvenance
from app.antigravity_acp import ensure_interactive_input
from app.session_state import DeliveryDeferred
from app.session_turns import TurnManager

USER = MessageProvenance("user", ("owner",))
CRON = MessageProvenance("platform", ("cron",), subtype="cron")


class _FakeSteerOwner:
    def __init__(self):
        self.home = Path("/tmp/synthetic-home")
        self.epoch = 1
        self.capabilities = {"sessionCapabilities": {"resume": {}}}
        self.sessions = {"sid-1"}
        self.listeners = {}
        self.permission_handlers = {}
        self.uncertain_sessions = set()
        self.recovery_cleanup_needed = False
        self.cost_totals = {"sid-1": 0.0}
        self.usage_totals = {"sid-1": {}}
        self.model_states = {
            "sid-1": {
                "current": "gemini-4-neon-high",
                "available": {"gemini-4-neon-high"},
                "config_id": None,
                "thought_config_id": None,
                "current_thought": None,
                "thought_available": set(),
                "legacy_available": set(),
            }
        }
        self.failure = None
        self._permanent_failure = False
        self._setup_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._session_locks = {}
        self.process = SimpleNamespace(returncode=None)
        self.prompts = []
        self.cancels = 0
        self.step_futures = {}
        self.step_started = {}
        self.usage_step = 0

    def published_models(self, _state=None):
        return {"gemini-4-neon-high"}

    def session_lock(self, sid):
        return self._session_locks.setdefault(sid, asyncio.Lock())

    @asynccontextmanager
    async def turn_slot(self, _backend):
        yield

    async def start(self):
        return None

    async def close(self, reason):
        self.failure = reason

    async def notify(self, method, params):
        if method == "session/cancel":
            self.cancels += 1
            idx = len(self.prompts) - 1
            fut = self.step_futures.get(idx)
            if fut and not fut.done():
                fut.set_result({"stopReason": "cancelled", "usage": {"input_tokens": 100, "output_tokens": 20}})

    async def request(self, method, params, *, before_write=None, on_written=None):
        if method == "session/prompt":
            idx = len(self.prompts)
            self.prompts.append(params)
            if before_write is not None:
                await before_write()
            if on_written is not None:
                on_written()
            fut = asyncio.get_running_loop().create_future()
            self.step_futures[idx] = fut
            ev = self.step_started.setdefault(idx, asyncio.Event())
            ev.set()
            return await fut
        return {}


def _make_backend(owner):
    ctx = SimpleNamespace(
        model="antigravity/gemini-4-neon-high",
        cwd="/tmp",
        system_prompt="role",
        mcp_servers={},
        context_limit=1000,
        resume_session_id="sid-1",
        profile="",
        effort=None,
    )
    b = agy.AntigravityBackend(ctx)
    b.home = owner.home
    b._owner = owner
    return b


def test_antigravity_capabilities_and_cron_guard_unchanged():
    rt = runtime_registry.get_runtime("antigravity")
    assert rt.capabilities.mid_turn_inject is True
    assert agy.AntigravityBackend.foreground_capabilities["mid_turn_injection"] is True
    assert agy.AntigravityBackend.foreground_capabilities["automated_prompts"] is False
    # Antigravity cron/timer ban must stay 100% intact.
    with pytest.raises(ValueError, match="antigravity_interactive_only"):
        ensure_interactive_input("antigravity/gemini-4-neon-high", CRON)
    ensure_interactive_input("gpt-6.2-sol", CRON)


@pytest.mark.asyncio
async def test_mid_turn_steer_waits_open_tool_cancels_and_runs_same_session(monkeypatch):
    from app import provider_safety
    monkeypatch.setattr(provider_safety, "verify_provider_egress", AsyncMock := (lambda *_: _noop_async()))
    monkeypatch.setattr(provider_safety, "record_provider_activity", lambda *_: None)
    monkeypatch.setattr(agy, "canonical_profile", lambda _p="": Path("/tmp/synthetic-home"))
    from app import native_requests
    monkeypatch.setattr(native_requests, "profile_epoch", lambda _h: 1)
    owner = _FakeSteerOwner()
    backend = _make_backend(owner)

    await backend.send(InjectedMessage("first step", USER, "ev1"))
    await backend.wait_for_submission()
    await owner.step_started.setdefault(0, asyncio.Event()).wait()

    # Open tool call active -> steer waits briefly, completes when tool closes, then cancels & re-prompts.
    backend._update({
        "sessionUpdate": "tool_call",
        "toolCallId": "t1",
        "name": "read_file",
        "status": "in_progress",
        "rawInput": {"Path": "a.py"},
    })

    before_called = False

    async def steer_before():
        nonlocal before_called
        before_called = True

    await backend.send(InjectedMessage("steer redirection", USER, "ev2"), before_submit=steer_before)
    waiter = asyncio.create_task(backend.wait_for_submission())
    await asyncio.sleep(0.03)
    assert owner.cancels == 0, "must grant open tool grace before session/cancel"

    # Complete open tool -> wakes immediately and triggers cancel -> prompt #2.
    backend._update({
        "sessionUpdate": "tool_call_update",
        "toolCallId": "t1",
        "status": "completed",
        "rawOutput": "ok",
    })
    await asyncio.wait_for(owner.step_started.setdefault(1, asyncio.Event()).wait(), timeout=2.0)
    await asyncio.wait_for(waiter, timeout=2.0)
    assert before_called is True
    assert owner.cancels == 1
    assert len(owner.prompts) == 2
    assert owner.prompts[1]["sessionId"] == "sid-1"
    assert owner.prompts[1]["prompt"][-1]["text"] == "steer redirection"

    # Finish step 2 -> exactly ONE turn_end with summed token deltas!
    owner.step_futures[1].set_result({"stopReason": "end_turn", "usage": {"input_tokens": 250, "output_tokens": 70}})
    events = [e async for e in backend.events()]
    await backend._task
    ends = [e for e in events if e.type == "turn_end"]
    assert len(ends) == 1
    assert ends[0].metadata["ok"] is True
    assert ends[0].metadata["input_tokens"] == 250
    assert ends[0].metadata["output_tokens"] == 70


@pytest.mark.asyncio
async def test_mid_turn_steer_end_turn_race_executes_steer_before_exit(monkeypatch):
    from app import provider_safety
    monkeypatch.setattr(provider_safety, "verify_provider_egress", lambda *_: _noop_async())
    monkeypatch.setattr(provider_safety, "record_provider_activity", lambda *_: None)
    monkeypatch.setattr(agy, "canonical_profile", lambda _p="": Path("/tmp/synthetic-home"))
    from app import native_requests
    monkeypatch.setattr(native_requests, "profile_epoch", lambda _h: 1)
    owner = _FakeSteerOwner()
    backend = _make_backend(owner)

    await backend.send(InjectedMessage("initial", USER, "ev1"))
    await backend.wait_for_submission()
    await owner.step_started.setdefault(0, asyncio.Event()).wait()

    # Queue steer right as step 0 resolves end_turn synchronously (race).
    await backend.send(InjectedMessage("late steer", USER, "ev2"))
    owner.step_futures[0].set_result({"stopReason": "end_turn", "usage": {"input_tokens": 50, "output_tokens": 10}})
    await asyncio.wait_for(backend.wait_for_submission(), timeout=2.0)
    await asyncio.wait_for(owner.step_started.setdefault(1, asyncio.Event()).wait(), timeout=2.0)
    assert owner.cancels == 0
    assert len(owner.prompts) == 2
    assert owner.prompts[1]["prompt"][-1]["text"] == "late steer"

    owner.step_futures[1].set_result({"stopReason": "end_turn", "usage": {"input_tokens": 90, "output_tokens": 25}})
    events = [e async for e in backend.events()]
    await backend._task
    assert sum(e.type == "turn_end" for e in events) == 1


@pytest.mark.asyncio
async def test_mid_turn_steer_rejects_non_interactive_cron(monkeypatch):
    from app import provider_safety
    monkeypatch.setattr(provider_safety, "verify_provider_egress", lambda *_: _noop_async())
    monkeypatch.setattr(provider_safety, "record_provider_activity", lambda *_: None)
    monkeypatch.setattr(agy, "canonical_profile", lambda _p="": Path("/tmp/synthetic-home"))
    from app import native_requests
    monkeypatch.setattr(native_requests, "profile_epoch", lambda _h: 1)
    owner = _FakeSteerOwner()
    backend = _make_backend(owner)

    await backend.send(InjectedMessage("initial", USER, "ev1"))
    await backend.wait_for_submission()
    await owner.step_started.setdefault(0, asyncio.Event()).wait()

    with pytest.raises(ValueError, match="antigravity_interactive_only"):
        await backend.send(InjectedMessage("cron poke", CRON, "ev-cron"))

    owner.step_futures[0].set_result({"stopReason": "end_turn"})
    [e async for e in backend.events()]
    await backend._task


@pytest.mark.asyncio
async def test_mailbox_quarantine_breaks_infinite_antigravity_retry_loop(tmp_path, monkeypatch):
    db.init_db()
    bad_id = mailbox.enqueue(
        recipient="agy-orch",
        scope=str(tmp_path),
        sender="dashboard",
        body="untrusted dashboard prompt",
        provenance=MessageProvenance("unknown", ("dashboard",), subtype="dashboard"),
    )
    good_id = mailbox.enqueue(
        recipient="agy-orch",
        scope=str(tmp_path),
        sender="owner",
        body="real user reply",
        provenance=MessageProvenance("user", ("owner",), subtype="dashboard_user"),
    )
    assert len(mailbox.pending("agy-orch", str(tmp_path))) == 2

    delivered = []
    fake_session = SimpleNamespace(
        name="agy-orch",
        scope=str(tmp_path),
        model="antigravity/gemini-4-neon-high",
        is_orchestrator=True,
        _delivering_mailbox=False,
        _delivery_depth=lambda: 0,
        _log=lambda *_a, **_kw: None,
    )

    async def fake_send(text, *, owner_initiated=True, provenance=None, **_kw):
        delivered.append((text, provenance.origin if provenance else None))

    fake_session.send = fake_send
    fake_session.notify_mailbox_delivered = lambda *_a, **_kw: None
    fake_session._is_busy_flag = False
    tm = TurnManager(fake_session)
    queued = mailbox.claim("agy-orch", str(tmp_path))
    await tm._deliver_mailbox(queued)

    # The disallowed dashboard row must be quarantined (never re-pending forever),
    # while the interactive user row was delivered cleanly.
    assert mailbox.pending("agy-orch", str(tmp_path)) == []
    with db._conn() as c:
        bad_row = c.execute("SELECT delivered_at, claimed_at FROM mailbox WHERE id = ?", (bad_id,)).fetchone()
        good_row = c.execute("SELECT delivered_at, claimed_at FROM mailbox WHERE id = ?", (good_id,)).fetchone()
    assert bad_row[0] is not None and bad_row[1] is None
    assert good_row[0] is not None
    assert any("real user reply" in text for text, _ in delivered)


def test_acp_tools_orchestra_wire_normalization():
    assert acp_tools.canonical_name({"name": "mcp_orchestra_0eaef74b_list_agents"}) == "mcp__orchestra__list_agents"
    assert acp_tools.canonical_name({"name": "mcp_orchestra_bg_list"}) == "mcp__orchestra__bg_list"
    assert acp_tools.canonical_name({"name": "mcp_orchestra_run_command"}) == "mcp_orchestra_run_command"
    assert acp_tools.canonical_name({"name": "mcp_unknown_custom"}) == "mcp_unknown_custom"


async def _noop_async():
    return None
