"""Offline lifecycle regressions for bounded turn segments (V-1289)."""

import asyncio
import importlib.util
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app import db, runaway_guard
from app.events import AgentEvent, MessageProvenance
from app.session import AgentSession, AgentStatus


@pytest_asyncio.fixture
async def session(tmp_path, monkeypatch):
    db.init_db()
    s = AgentSession(
        id="turn-cap", name="turn-cap", scope=str(tmp_path), cwd=str(tmp_path),
        model="gpt-6-luna", backend_type="codex", role="orchestrator",
        created_at=datetime.now(timezone.utc),
    )
    s._persist = MagicMock()
    s._log = MagicMock()
    s._start_checklist_reminder = MagicMock()
    s._wake_durable_message_deliveries = MagicMock()
    s._hibernate.schedule = MagicMock()
    s._turns.fire_auto_report = MagicMock()
    s._turns.report_abnormal_end = MagicMock(wraps=s._turns.report_abnormal_end)
    s.scheduled = []

    def discard(coroutine):
        s.scheduled.append(coroutine.cr_code.co_name)
        coroutine.close()

    s._spawn_bg = discard
    monkeypatch.setattr("app.mailbox.claim", lambda *_: [])
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    s._start_turn_state()
    return s


def backend():
    return SimpleNamespace(interrupt=AsyncMock(return_value=True), disconnect=AsyncMock())


def test_orchestrator_default_and_environment_override(monkeypatch):
    def load():
        spec = importlib.util.spec_from_file_location("isolated_guard", runaway_guard.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    monkeypatch.delenv("ORCHESTRA_MAX_ORCHESTRATOR_TOOLS_PER_TURN", raising=False)
    default = load()
    assert default.MAX_ORCHESTRATOR_TOOLS_PER_TURN == 250
    assert default.turn_limit_reason(249, 0, orchestrator=True) == ""
    assert default.turn_limit_reason(250, 0, orchestrator=True) == "tool_limit"
    monkeypatch.setenv("ORCHESTRA_MAX_ORCHESTRATOR_TOOLS_PER_TURN", "17")
    overridden = load()
    assert overridden.turn_limit_reason(16, 0, orchestrator=True) == ""
    assert overridden.turn_limit_reason(17, 0, orchestrator=True) == "tool_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,tools,elapsed,detail", [
    ("tool_limit", 250, 12, "250 tools"),
    ("wall_limit", 3, 3600, "3600s"),
])
async def test_checkpoint_continues_without_terminal_side_effects(session, reason, tools, elapsed, detail):
    old = session._backend = backend()
    gen = session._turn_gen
    session.session_id = "retained-native-session"
    await session._checkpoint_runaway_turn(old, reason, tools, elapsed, turn_gen=gen)

    old.interrupt.assert_awaited_once()
    old.disconnect.assert_awaited_once()
    assert session._backend is None
    assert session.session_id == "retained-native-session"
    assert session.status == AgentStatus.IDLE
    assert session._turn_start == 0
    assert session._auto_continue_count == 1
    assert not session._manually_interrupted
    assert not session._turn_finished_event.is_set()
    assert session.scheduled == ["_auto_continue"]
    session._log.assert_called_once_with(
        "status", f"{reason} ({detail}), auto-continuing (1/5)",
    )
    session._turns.fire_auto_report.assert_not_called()
    session._turns.report_abnormal_end.assert_not_called()
    session._hibernate.schedule.assert_not_called()

    # The listener's done callback must not release terminal fan-out waiters either.
    listener = session._listen_task = MagicMock()
    listener.exception.return_value = None
    session._on_task_done(listener)
    assert not session._turn_finished_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["tool_limit", "wall_limit"])
async def test_one_budget_is_consumed_across_segments_then_exhausted(session, reason):
    for index in range(session.AUTO_CONTINUE_MAX + 1):
        if index:
            session._start_turn_state(auto_continuation=True)
        old = session._backend = backend()
        await session._checkpoint_runaway_turn(old, reason, 250, 3600, turn_gen=session._turn_gen)
        assert session._auto_continue_count == min(index + 1, session.AUTO_CONTINUE_MAX)
        assert session._turn_finished_event.is_set() == (index == session.AUTO_CONTINUE_MAX)

    assert session.scheduled.count("_auto_continue") == session.AUTO_CONTINUE_MAX
    assert session.status == AgentStatus.IDLE
    assert not session._manually_interrupted
    errors = [call.args[1] for call in session._log.call_args_list if call.args[0] == "error"]
    assert errors == [f"{reason}: auto-continue cap reached (5)"]
    session._turns.report_abnormal_end.assert_called_once_with(errors[0])
    assert not session._last_turn_ok


@pytest.mark.asyncio
async def test_native_and_runaway_limits_share_the_budget(session):
    session._auto_continue_count = 4
    session._handle_event(AgentEvent("turn_end", metadata={
        "ok": True, "stop_reason": "max_turns", "num_turns": 5,
    }))
    assert session._auto_continue_count == 5
    session._start_turn_state(auto_continuation=True)
    old = session._backend = backend()
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 10, turn_gen=session._turn_gen)
    assert session.scheduled.count("_auto_continue") == 1
    assert session._turn_finished_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["generation", "backend", "idle", "manual"])
async def test_stale_or_manually_stopped_checkpoint_cannot_interrupt(session, change):
    old = session._backend = backend()
    gen = session._turn_gen
    if change == "generation":
        session._start_turn_state()
    elif change == "backend":
        session._backend = backend()
    elif change == "idle":
        session.status = AgentStatus.IDLE
    else:
        session._manually_interrupted = True
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 1, turn_gen=gen)
    old.interrupt.assert_not_awaited()
    old.disconnect.assert_not_awaited()
    assert session.scheduled == []


@pytest.mark.asyncio
async def test_checkpoint_rechecks_generation_after_provider_await(session):
    old = session._backend = backend()
    newer = backend()

    async def supersede():
        session._start_turn_state()
        session._backend = newer
        return True

    old.interrupt.side_effect = supersede
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 1, turn_gen=session._turn_gen)
    assert session.status == AgentStatus.RUNNING
    assert session._backend is newer
    old.disconnect.assert_not_awaited()
    newer.interrupt.assert_not_awaited()
    assert session.scheduled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, RuntimeError("interrupt channel failed"), asyncio.TimeoutError()])
async def test_failed_interrupt_still_retires_old_stream_and_continues(session, outcome):
    old = session._backend = backend()
    if outcome is False:
        old.interrupt.return_value = False
    else:
        old.interrupt.side_effect = outcome
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 1, turn_gen=session._turn_gen)
    old.disconnect.assert_awaited_once()
    assert session._backend is None
    assert session.scheduled == ["_auto_continue"]
    assert not session._manually_interrupted
    assert not any(call.args[0] == "error" for call in session._log.call_args_list)


@pytest.mark.asyncio
async def test_failed_disconnect_does_not_start_an_overlapping_turn(session):
    old = session._backend = backend()
    old.disconnect.side_effect = RuntimeError("disconnect failed")
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 1, turn_gen=session._turn_gen)
    assert session.scheduled == []
    assert session._turn_finished_event.is_set()
    session._log.assert_any_call("error", "tool_limit: provider disconnect failed (RuntimeError)")


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["tool", "elapsed", "silence"])
async def test_event_loop_enforces_boundary_without_reporting_completion(session, monkeypatch, boundary):
    closed = []

    async def events():
        try:
            if boundary == "silence":
                await asyncio.Event().wait()
            for _ in range(10):
                yield AgentEvent("tool_use", "read")
            pytest.fail("the old provider stream must not reach its late terminal")
        finally:
            closed.append(True)

    monkeypatch.setattr(runaway_guard, "MAX_ORCHESTRATOR_TOOLS_PER_TURN", 2)
    if boundary != "tool":
        monkeypatch.setattr(runaway_guard, "MAX_TURN_WALL_SECONDS", 0.01)
    if boundary == "elapsed":
        session._turn_start -= 2
    old = session._backend = backend()
    old.events = events
    await session._turn_event_loop()
    assert session._auto_continue_count == 1
    assert session.status == AgentStatus.IDLE
    assert not session._turn_finished_event.is_set()
    assert not session._manually_interrupted
    assert session.scheduled == ["_auto_continue"]
    assert closed == ([] if boundary == "elapsed" else [True])
    session._turns.fire_auto_report.assert_not_called()
    session._turns.report_abnormal_end.assert_not_called()
    session._hibernate.schedule.assert_not_called()
    assert not any(call.args[0] in {"warning", "error"} for call in session._log.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["max_turns", "error_max_turns"])
async def test_native_limit_listener_does_not_report_or_publish_terminal(session, reason):
    async def events():
        yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": reason})

    session._backend = SimpleNamespace(events=events, active_turn_id=None)
    await session._turn_event_loop()
    assert session._auto_continue_count == 1
    assert session.status == AgentStatus.IDLE
    assert not session._turn_finished_event.is_set()
    session._turns.fire_auto_report.assert_not_called()
    session._turns.report_abnormal_end.assert_not_called()
    session._hibernate.schedule.assert_not_called()


@pytest.mark.asyncio
async def test_continuation_with_no_terminal_is_still_reported_as_a_failure(session):
    session._auto_continue_count = 1
    session._last_stop_reason = "max_turns"
    session._start_turn_state(auto_continuation=True)

    async def events():
        return
        yield

    session._backend = SimpleNamespace(events=events, active_turn_id=None)
    await session._turn_event_loop()
    assert session.status == AgentStatus.IDLE
    assert session._turn_finished_event.is_set()
    session._turns.report_abnormal_end.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["manual_stop", "new_turn"])
async def test_pending_auto_continue_yields_to_stop_or_new_turn(session, monkeypatch, action):
    old = session._backend = backend()
    await session._checkpoint_runaway_turn(old, "tool_limit", 250, 1, turn_gen=session._turn_gen)
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(_delay):
        entered.set()
        await release.wait()

    monkeypatch.setattr("app.session.asyncio.sleep", pause)
    session.send = AsyncMock()
    pending = asyncio.create_task(session._auto_continue(session._turn_gen))
    try:
        await entered.wait()
        if action == "manual_stop":
            await session.interrupt()
            assert session._manually_interrupted
            assert session._turn_finished_event.is_set()
        else:
            session._start_turn_state()
            assert session._auto_continue_count == 0
        release.set()
        await pending
        session.send.assert_not_awaited()
    finally:
        release.set()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_manual_interrupt_wins_before_waiting_checkpoint_acquires_lock(session):
    old = session._backend = backend()

    async def acknowledge():
        session.status = AgentStatus.IDLE
        session._turns.publish_turn_finished()
        return True

    old.interrupt.side_effect = acknowledge
    await session._lifecycle_lock.acquire()
    stop = asyncio.create_task(session.interrupt())
    checkpoint = asyncio.create_task(session._checkpoint_runaway_turn(
        old, "tool_limit", 250, 1, turn_gen=session._turn_gen,
    ))
    session._lifecycle_lock.release()
    await asyncio.gather(stop, checkpoint)
    old.interrupt.assert_awaited_once()
    old.disconnect.assert_not_awaited()
    assert session._manually_interrupted
    assert session.scheduled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation", [False, True])
async def test_real_send_resets_only_normal_turn_budget(session, monkeypatch, continuation):
    session.status = AgentStatus.IDLE
    session._auto_continue_count = 3
    observed = []
    old = backend()

    async def send(_message):
        observed.append(session._auto_continue_count)

    async def events():
        yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": "end_turn"})

    async def ensure(**_kwargs):
        session._backend = old
        return old

    old.send = send
    old.events = events
    session._ensure_backend = ensure
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._attach_pending_facts = lambda message: (message, ())
    session._ack_pending_facts = MagicMock()
    session._notify_scope_running = AsyncMock()
    monkeypatch.setattr(session._turns, "_compact_codex_before_limit", MagicMock())
    provenance = MessageProvenance(
        origin="system" if continuation else "user", senders=("system" if continuation else "user",),
        subtype="turn_limit_continue" if continuation else "",
    )
    await session.send(
        "continue" if continuation else "new task", provenance=provenance,
        retry_generation=(session._turn_gen, session._turn_start_cancel_gen) if continuation else None,
    )
    await session._listen_task
    assert observed == [3 if continuation else 0]
    assert session._auto_continue_count == 0
    assert session._turn_finished_event.is_set()
    assert session.status == AgentStatus.IDLE
    session._turns.fire_auto_report.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["tool_limit", "wall_limit"])
async def test_scheduled_auto_continue_reaches_a_real_next_turn(session, monkeypatch, reason):
    old = session._backend = backend()
    new = backend()
    new.send = AsyncMock()
    continuation_tasks = []

    async def events():
        yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": "end_turn"})

    async def ensure(**_kwargs):
        assert old.disconnect.await_count == 1
        session._backend = new
        return new

    def spawn(coroutine):
        if coroutine.cr_code.co_name == "_auto_continue":
            continuation_tasks.append(asyncio.create_task(coroutine))
        else:
            coroutine.close()

    session._spawn_bg = spawn
    new.events = events
    session._ensure_backend = ensure
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._attach_pending_facts = lambda message: (message, ())
    session._ack_pending_facts = MagicMock()
    session._notify_scope_running = AsyncMock()
    monkeypatch.setattr(session._turns, "_compact_codex_before_limit", MagicMock())
    monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())
    gen = session._turn_gen
    await session._checkpoint_runaway_turn(old, reason, 250, 3600, turn_gen=gen)
    assert not session._turn_finished_event.is_set()
    await asyncio.gather(*continuation_tasks)
    await session._listen_task
    assert session._turn_gen == gen + 1
    new.send.assert_awaited_once_with("[system] Turn limit reached. Continue where you left off.")
    assert session._auto_continue_count == 0
    assert session._turn_finished_event.is_set()
    session._turns.fire_auto_report.assert_called_once()
    session._turns.report_abnormal_end.assert_not_called()

