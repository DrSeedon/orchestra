"""Synthetic offline Codex refusal -> durable continuation regressions (V-1081)."""

import json
import asyncio
import time
from uuid import uuid4
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import limit_wake
from app.backend_codex import CodexBackend
from app.session import AgentSession
from app.events import MessageProvenance
from app.session_state import AgentStatus


@pytest.mark.parametrize("terminal_only", [False, True])
def test_native_refusal_survives_session_logs(terminal_only):
    backend = CodexBackend(model="gpt-6.1-sol", cwd="/scope")
    error = {"codexErrorInfo": "usageLimitExceeded", "message": "synthetic quota refusal"}
    notification = (
        {"method": "turn/completed", "params": {"turn": {
            "id": "quota-turn", "status": "failed", "error": error,
        }}}
        if terminal_only else {"method": "error", "params": {"error": error}}
    )
    session = AgentSession(id="native", name="native", scope="/scope", cwd="/scope",
                           backend_type="codex", model="gpt-6.1-sol")
    rows = [{"id": 1, "type": "user_message", "content": "work", "origin": "user"}]
    session._log = lambda kind, content, **kw: rows.append({
        "id": len(rows) + 1, "type": kind, "content": content,
    })
    session._spawn_bg = Mock(side_effect=lambda coro: coro.close())
    for event in backend._convert_notification(notification):
        if event.type != "turn_end":
            session._handle_event(event)
    rows.append({"id": len(rows) + 1, "type": "status", "content": "turn ended (failed)"})
    candidates = limit_wake.find_limit_stopped_agents([
        {"id": "native", "name": "native", "model": session.model, "status": "idle"},
    ], {"native": rows})
    assert len(candidates) == 1
    record = json.loads(next(row["content"] for row in rows if row["type"] == "provider_limit"))
    assert record["status"] == "rejected"


@pytest.mark.parametrize("provider", ["codex", "codex_spark"])
@pytest.mark.parametrize("windows", [
    [{"id": "primary", "utilization": 100, "resets_at": "2000-01-01T00:00:00Z"}],
    [{"id": "primary", "utilization": 0}, {"id": "secondary", "utilization": None}],
    [{"id": "primary", "utilization": False}],
    [{"id": "primary", "utilization": float("nan")}],
])
def test_codex_capacity_needs_actual_complete_observation(provider, windows):
    result = limit_wake.provider_readiness({"fresh": True, "usage": {"windows": windows}}, provider)
    assert result["state"] != "available"


def test_codex_fresh_open_window_can_reset_early():
    now = datetime.now(timezone.utc)
    plan = limit_wake.build_wake_plan([
        {"id": "a", "name": "a", "scope": "/scope", "provider": "codex",
         "limit_turn_id": 3, "limit_reset_at": (now + timedelta(days=1)).isoformat()},
    ], {"codex": {"fresh": True, "usage": {"windows": [
        {"id": "primary", "utilization": 0},
    ]}}}, now=now)
    assert plan["schedules"][0]["reason"] == "available_now"


@pytest.fixture
def native_env(tmp_path, monkeypatch):
    from app import db, deps, initial_delivery_events, message_deliveries, quota_gate, report_holds
    from app.manager import SessionManager
    from app.routes import system

    db.init_db()
    session = AgentSession(id="native", name="native", scope=str(tmp_path), cwd=str(tmp_path),
                           backend_type="codex", model="gpt-6.1-sol", session_id="native-thread")
    session._turn_gen = 1
    session._log = lambda kind, content, **kw: db.add_log(
        session.id, datetime.now(timezone.utc), kind, content, **kw,
    )
    session._persist = lambda: db.save_session(session._to_db_dict())
    session._submit_db_write = Mock()
    scheduled = []

    def spawned(coro):
        if coro.cr_code.co_name == "schedule_wake_auto":
            scheduled.append(coro)
        else:
            coro.close()

    session._spawn_bg = spawned
    session._notify_scope_running = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._hibernate.schedule = Mock()
    backend = SimpleNamespace(send=AsyncMock(), active_turn_id="resumed-turn", resume_failed=False)
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._persist()
    manager = SessionManager()
    manager.sessions[session.id] = session
    monkeypatch.setattr(deps, "manager", manager)
    monkeypatch.setattr(report_holds, "ensure_runner", Mock())
    monkeypatch.setattr(initial_delivery_events, "ensure_runner", Mock())
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", Mock())
    monkeypatch.setattr(limit_wake, "_last_auto_schedule", None)
    monkeypatch.setattr(system, "_codex_usage_cache", {"data": None, "ts": 0})
    windows = [{"id": key, "utilization": 0, "window_minutes": minutes,
                "resets_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()}
               for key, minutes in (("primary", 300), ("secondary", 10080))]
    env = SimpleNamespace(session=session, manager=manager, backend=backend, scheduled=scheduled,
                          db=db, snapshot={"codex": {"windows": windows},
                                           "codex_spark": {"windows": [dict(window) for window in windows]}},
                          weekly_closed=False, refresh_error=None)

    async def refresh(**kw):
        assert kw["force_refresh"] is True
        if env.refresh_error:
            raise env.refresh_error
        return env.snapshot

    async def admission(model, **kw):
        provider = quota_gate.quota_bucket_for_model(model)
        decision = quota_gate.evaluate_worker_admission(model, env.snapshot, {provider: time.time()})
        return replace(decision, state="blocked", utilization=98, reason="synthetic weekly gate") \
            if env.weekly_closed else decision

    env.refresh = AsyncMock(side_effect=refresh)
    env.admission = AsyncMock(side_effect=admission)
    monkeypatch.setattr(system, "current_provider_usage", env.refresh)
    monkeypatch.setattr(quota_gate, "get_worker_admission", env.admission)
    yield env
    for coro in scheduled:
        coro.close()


def _refuse(env, *, code="usageLimitExceeded", origin="user", subtype="", terminal_only=False):
    session = env.session
    session.status = AgentStatus.RUNNING
    session._persist()
    session._log("user_message", "synthetic task", provenance=MessageProvenance(
        origin=origin, senders=("test",), subtype=subtype,
    ))
    backend = CodexBackend(model=session.model, cwd=session.cwd)
    backend._thread_id = session.session_id
    error = {"codexErrorInfo": code, "message": "synthetic quota refusal"}
    if not terminal_only:
        for event in backend._convert_notification({"method": "error", "params": {"error": error}}):
            session._handle_event(event)
    for event in backend._convert_notification({"method": "turn/completed", "params": {
        "turn": {"id": f"quota-{session._turn_gen}", "status": "failed", "error": error},
    }}):
        session._handle_event(event)


async def _schedule(env):
    pending = list(env.scheduled)
    env.scheduled.clear()
    for coro in pending:
        await coro


def _receipts(env):
    with env.db._conn() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM message_deliveries ORDER BY accept_seq")]


async def _release_and_run(env):
    from app import quota_queue, message_deliveries

    released = await quota_queue.release_waiting()
    await message_deliveries.run_target_message_deliveries(env.session.id, manager=env.manager)
    return released


@pytest.mark.asyncio
@pytest.mark.parametrize("orchestrator", [False, True])
@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-luna", "gpt-5.3-codex-spark"])
async def test_backend_through_scheduler_queue_and_real_session_send_once(native_env, orchestrator, model):
    env = native_env
    env.session.is_orchestrator = orchestrator
    env.session.model = model
    _refuse(env, terminal_only=orchestrator)
    assert env.session.status == AgentStatus.IDLE
    assert len(env.scheduled) == 1
    await _schedule(env)
    receipts = _receipts(env)
    assert [row["state"] for row in receipts] == ["WAITING_QUOTA"]
    assert not env.backend.send.called
    assert await _release_and_run(env) == 1
    assert _receipts(env)[0]["state"] == "SUBMITTED", _receipts(env)[0]["error_json"]
    env.backend.send.assert_awaited_once()
    assert env.admission.await_count == 2  # release and submission, including orchestrators
    text = env.backend.send.await_args.args[0]
    assert text.startswith(limit_wake.WAKE_MESSAGE_PREFIX + _receipts(env)[0]["delivery_id"] + "]")
    assert await _release_and_run(env) == 0
    assert _receipts(env)[0]["delivery_id"] == receipts[0]["delivery_id"]
    env.backend.send.assert_awaited_once()
    with env.db._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM bg_jobs").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["past_reset", "unknown_window", "no_reset", "stale", "weekly"])
async def test_capacity_wait_survives_restart_until_fresh_open(native_env, case):
    from app import message_deliveries

    env = native_env
    _refuse(env)
    await _schedule(env)
    if case == "stale":
        env.refresh_error = RuntimeError("synthetic refresh failure; stale cache exists")
    elif case == "weekly":
        env.weekly_closed = True
    else:
        env.snapshot["codex"]["windows"][1]["utilization"] = None if case == "unknown_window" else 100
        env.snapshot["codex"]["windows"][1]["resets_at"] = (
            "2000-01-01T00:00:00Z" if case == "past_reset" else None
        )
    assert await _release_and_run(env) == 0
    assert _receipts(env)[0]["state"] == "WAITING_QUOTA"
    env.backend.send.assert_not_awaited()
    # Existing startup recovery leaves the accepted, unsubmitted owner intact.
    await message_deliveries.recover_message_deliveries()
    env.session._codex_limit_wake_generation = None  # freshly hydrated instance
    env.refresh_error = None
    env.weekly_closed = False
    env.snapshot["codex"]["windows"][1]["utilization"] = 0
    assert await _release_and_run(env) == 1
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["manual", "new_user", "archive", "task", "model", "branch", "native", "needs_switch", "generation", "cancel"])
async def test_superseded_interruption_never_sends(native_env, guard):
    from app import message_deliveries

    env = native_env
    _refuse(env)
    await _schedule(env)
    session = env.session
    if guard == "manual":
        await session.interrupt()
    elif guard == "new_user":
        session._log("user_message", "new user instruction", provenance=MessageProvenance(
            origin="user", senders=("owner",),
        ))
    elif guard == "archive":
        with env.db._conn() as connection:
            connection.execute("UPDATE sessions SET status='archived' WHERE id=?", (session.id,))
    elif guard == "generation":
        session._turn_gen += 1  # log persistence may lag the in-memory lifecycle
    elif guard == "cancel":
        message_deliveries.cancel_message_delivery(_receipts(env)[0]["delivery_id"], None)
    else:
        setattr(session, {"task": "task_id", "native": "session_id"}.get(guard, guard),
                True if guard == "needs_switch" else "new-generation")
        session._persist()
    await _release_and_run(env)
    await limit_wake.queue_codex_limit_wakes()
    env.backend.send.assert_not_awaited()
    assert len(_receipts(env)) == 1


@pytest.mark.asyncio
async def test_crash_before_acceptance_and_repeat_refusal_get_one_owner_per_turn(native_env):
    env = native_env
    _refuse(env)
    # Lose the in-memory scheduler callback; the existing quota sweep recovers.
    for coro in env.scheduled:
        coro.close()
    env.scheduled.clear()
    assert await _release_and_run(env) == 1
    assert len(_receipts(env)) == 1
    # The continued turn can genuinely exhaust a later window.
    _refuse(env, code="sessionBudgetExceeded", origin="system", subtype="limit_wake")
    await _schedule(env)  # still inside the debounce window
    assert len(_receipts(env)) == 2
    assert await _release_and_run(env) == 1
    assert env.backend.send.await_count == 2


@pytest.mark.asyncio
async def test_ambiguous_dispatch_is_never_replayed(native_env):
    from app import message_deliveries

    env = native_env
    _refuse(env)
    await _schedule(env)
    env.backend.send.side_effect = RuntimeError("synthetic uncertain provider acceptance")
    with pytest.raises(RuntimeError, match="synthetic uncertain"):
        await _release_and_run(env)
    assert _receipts(env)[0]["state"] == "DELIVERY_UNKNOWN"
    await message_deliveries.recover_message_deliveries()
    await limit_wake.queue_codex_limit_wakes()
    await _release_and_run(env)
    env.backend.send.assert_awaited_once()
    assert _receipts(env)[0]["state"] == "DELIVERY_UNKNOWN_ORPHANED"


@pytest.mark.asyncio
async def test_incidental_notice_and_ordinary_completed_turn_have_no_wake(native_env):
    env = native_env
    _refuse(env, origin="platform", subtype="rules_link")
    await _schedule(env)
    assert not _receipts(env)
    env.session._session_limit_hit = False
    backend = CodexBackend(model=env.session.model, cwd=env.session.cwd)
    env.session._handle_event(backend._turn_completed({"id": "ordinary", "status": "completed"})[-1])
    assert not env.scheduled
    assert await _release_and_run(env) == 0
    env.backend.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["done", "cancelled"])
async def test_task_completion_cancels_waiting_continuation(native_env, monkeypatch, status):
    from app import tm

    env = native_env
    env.session.task_id = "1081"
    _refuse(env)
    await _schedule(env)
    monkeypatch.setattr(tm, "get_project_by_scope", lambda *a: {"id": "synthetic-project"})
    monkeypatch.setattr(tm, "resolve_task_ref", lambda *a: {"status": status})
    assert await _release_and_run(env) == 0
    assert _receipts(env)[0]["state"] == "CANCELLED"
    env.backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_while_submission_admission_awaits_is_rechecked(native_env):
    from app.quota_gate import evaluate_worker_admission

    env = native_env
    _refuse(env)
    await _schedule(env)
    calls = 0

    async def admission(model, **kw):
        nonlocal calls
        calls += 1
        if calls == 2:  # send() has released its lifecycle lock for admission
            await env.session.interrupt()
        return evaluate_worker_admission(model, env.snapshot, {"codex": time.time()})

    env.admission.side_effect = admission
    await _release_and_run(env)
    assert _receipts(env)[0]["state"] == "FAILED_BEFORE_SUBMIT"
    env.backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_new_user_instruction_supersedes_wake_and_sends_normally(native_env):
    from app import message_deliveries
    from uuid import uuid4

    env = native_env
    _refuse(env)
    await _schedule(env)
    await message_deliveries.accept_message_delivery(
        delivery_id=str(uuid4()), source_principal="owner", source_scope=env.session.scope,
        target_session_id=env.session.id, target_name=env.session.name, target_scope=env.session.scope,
        target_generation=limit_wake._wake_generation(env.session._to_db_dict()),
        message="new user work", rendered_message="new user work",
        provenance=MessageProvenance(origin="user", senders=("owner",)),
    )
    await _release_and_run(env)
    assert [row["state"] for row in _receipts(env)] == ["CANCELLED", "SUBMITTED"]
    env.backend.send.assert_awaited_once_with("new user work")


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-5.3-codex-spark"])
async def test_unknown_raw_window_cannot_vanish_in_display_projection(native_env, model):
    from app.routes import system

    env = native_env
    env.session.model = model
    _refuse(env)
    await _schedule(env)
    raw = {"rateLimitsByLimitId": {
        key: {"primary": {"usedPercent": 0, "windowDurationMins": 300},
              "secondary": {"usedPercent": "unknown", "windowDurationMins": 10080}}
        for key in ("codex", "codex_bengalfox")
    }}
    env.snapshot = system._provider_usage_snapshot(None, system._normalize_codex_usage(raw), None)
    assert await _release_and_run(env) == 0
    assert _receipts(env)[0]["state"] == "WAITING_QUOTA"
    env.backend.send.assert_not_awaited()


def test_manual_stop_before_terminal_record_survives_restart():
    rows = [
        {"id": 1, "type": "user_message", "content": "work", "origin": "user"},
        {"id": 2, "type": "provider_limit", "content": json.dumps({"status": "rejected"})},
        {"id": 3, "type": "status", "content": "interrupt requested"},
        {"id": 4, "type": "status", "content": "turn ended (interrupted)"},
    ]
    assert limit_wake._latest_limit_turn(rows) is None


@pytest.mark.asyncio
async def test_legacy_text_and_malformed_old_record_do_not_invent_recoverable_work(native_env):
    env = native_env
    env.session._log("error", "квота Codex исчерпана, сброс primary неизвестно")
    env.session._log("provider_limit", "malformed old record")
    env.session._log("status", "turn ended (failed)")
    assert await _release_and_run(env) == 0
    assert not _receipts(env)


@pytest.mark.asyncio
async def test_ordinary_user_turn_keeps_existing_allowed_path(native_env):
    env = native_env
    await env.manager.send(env.session.id, "ordinary allowed work", provenance=MessageProvenance(
        origin="user", senders=("owner",),
    ))
    env.backend.send.assert_awaited_once_with("ordinary allowed work")
    env.refresh.assert_not_awaited()
    assert not _receipts(env)


@pytest.mark.asyncio
async def test_duplicate_schedulers_share_one_durable_owner(native_env):
    env = native_env
    _refuse(env)
    await asyncio.gather(limit_wake.queue_codex_limit_wakes(), limit_wake.queue_codex_limit_wakes())
    await _schedule(env)
    assert len(_receipts(env)) == 1
    assert await _release_and_run(env) == 1
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_terminal_records_keep_native_turn_ownership(native_env):
    env = native_env
    _refuse(env)
    await _schedule(env)
    backend = CodexBackend(model=env.session.model, cwd=env.session.cwd)
    backend._thread_id = env.session.session_id
    for event in backend._turn_completed({
        "id": "quota-1", "status": "failed",
        "error": {"codexErrorInfo": "usageLimitExceeded", "message": "duplicate refusal"},
    }):
        env.session._handle_event(event)
    await _schedule(env)
    assert len(_receipts(env)) == 1
    assert await _release_and_run(env) == 1
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_spark_capacity_never_borrows_codex_windows(native_env):
    env = native_env
    env.session.model = "gpt-5.3-codex-spark"
    _refuse(env)
    await _schedule(env)
    env.snapshot["codex_spark"]["windows"][0]["utilization"] = 100
    assert await _release_and_run(env) == 0
    env.snapshot["codex_spark"]["windows"][0]["utilization"] = 0
    env.snapshot["codex"]["windows"][0]["utilization"] = 100
    assert await _release_and_run(env) == 1
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_actual_weekly_rule_blocks_open_provider_capacity(native_env):
    env = native_env
    _refuse(env)
    await _schedule(env)
    env.snapshot["codex"]["windows"][1]["utilization"] = 96
    assert await _release_and_run(env) == 0
    env.backend.send.assert_not_awaited()
    env.snapshot["codex"]["windows"][1]["utilization"] = 0
    assert await _release_and_run(env) == 1
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_queue_mark_does_not_claim_it_will_never_wake_without_a_timer(native_env):
    env = native_env
    _refuse(env)
    await _schedule(env)
    agent, = limit_wake._load_limit_stopped_agents()
    mark = limit_wake._mark_for(agent, [])
    assert mark["state"] == "scheduled" and mark["wake_at"] is None


@pytest.mark.asyncio
async def test_failure_before_provider_submit_is_visible_and_never_claimed_delivered(native_env):
    env = native_env
    _refuse(env)
    await _schedule(env)
    env.session._ensure_backend.side_effect = RuntimeError("synthetic backend unavailable")
    assert await _release_and_run(env) == 1
    assert _receipts(env)[0]["state"] == "FAILED_BEFORE_SUBMIT"
    env.backend.send.assert_not_awaited()


def _claude_session(env, model="claude-sonnet-5-5"):
    env.session.model = model
    env.session.backend_type = "claude"
    env.session.is_orchestrator = True  # skip worker admission: unrelated to the discriminant
    env.session._persist()


@pytest.mark.asyncio
async def test_legacy_claude_timer_wake_reaches_real_manager_send(native_env):
    env = native_env
    _claude_session(env)
    ref = uuid4().hex
    await env.manager.send(env.session.id, f"[system wake:{ref}] resume", provenance=MessageProvenance(
        origin="system", senders=("system",), subtype="limit_wake", ref=ref,
    ))
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_waiting_quota_limit_wake_delivery_end_to_end(native_env, monkeypatch):
    from app import message_deliveries, quota_queue
    from app.message_deliveries import accept_message_delivery

    env = native_env
    _claude_session(env)
    monkeypatch.setattr(quota_queue, "_admission_allows", AsyncMock(return_value=(True, None)))
    ref = uuid4().hex
    message = f"[system wake:{ref}] resume"
    await accept_message_delivery(
        delivery_id=ref, source_principal="background_job:wake", source_name="system",
        source_scope=env.session.scope, target_session_id=env.session.id, target_name="native",
        target_scope=env.session.scope, target_task_id="",
        target_generation=(f"session={env.session.id}|task={env.session.task_id}|"
                           f"branch={env.session.branch}|needs_switch=0"),
        message=message, rendered_message=message,
        provenance=MessageProvenance(origin="system", senders=("system",), subtype="limit_wake", ref=ref),
        quota_wait=limit_wake._codex_wait_decision(env.session.model, "waiting"),
    )
    assert _receipts(env)[0]["state"] == "WAITING_QUOTA"
    assert await _release_and_run(env) == 1
    assert _receipts(env)[0]["state"] == "SUBMITTED", _receipts(env)[0]["error_json"]
    env.backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_codex_receipt_stays_refused_after_switch_to_claude(native_env, monkeypatch):
    from app import quota_queue

    env = native_env
    _refuse(env)
    await _schedule(env)
    assert [row["state"] for row in _receipts(env)] == ["WAITING_QUOTA"]
    _claude_session(env)
    monkeypatch.setattr(quota_queue, "_admission_allows", AsyncMock(return_value=(True, None)))
    assert await _release_and_run(env) == 0
    assert _receipts(env)[0]["state"] == "CANCELLED"
    env.backend.send.assert_not_awaited()
