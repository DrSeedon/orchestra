import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest


def _session():
    from app.session import AgentSession

    session = AgentSession(
        id="owner-turn", name="child", scope="/scope", cwd=".",
        parent_name="parent", last_task_sender="parent",
        created_at=datetime.now(timezone.utc),
    )
    session.on_idle = AsyncMock()
    session._log = Mock()
    session._persist = Mock()
    session._turn_logs = ["work completed"]
    return session


async def _run_one_turn(session, provenance, monkeypatch):
    from app import db, fan_barrier
    from app.events import AgentEvent
    from app.session_state import AgentStatus
    from tests.test_session import _quota_decision

    db.init_db()
    session.model = "gpt-5.6-sol"
    session.backend_type = "codex"

    class Backend:
        async def send(self, _message):
            pass

        async def events(self):
            yield AgentEvent("text", "completed work")
            yield AgentEvent("turn_end", metadata={
                "ok": True,
                "stop_reason": "end_turn",
                "num_turns": 1,
                "cost_usd": 0,
            })

    backend = Backend()

    async def ensure_backend(**_kwargs):
        session._backend = backend
        return backend

    session._ensure_backend = ensure_backend
    session._admission_service = AsyncMock(
        return_value=_quota_decision(model=session.model),
    )
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._attach_pending_facts = lambda message: (message, ())
    session._ack_pending_facts = Mock()
    session._notify_scope_running = AsyncMock()
    session._turns.after_turn_idle_actions = lambda *_args, **_kwargs: session._turns.fire_auto_report()
    session._turns.cancel_auto_report()
    session.status = AgentStatus.IDLE
    monkeypatch.setattr(fan_barrier, "should_buffer", lambda *_args: False)
    monkeypatch.setattr(session, "_persist", Mock())

    await session.send("work", provenance=provenance)
    await session._listen_task
    if session._auto_report_task is not None:
        await session._auto_report_task


@pytest.mark.asyncio
@pytest.mark.parametrize("provenance", [
    ("user", ("user",), "http_send"),
    ("unknown", ("dashboard",), "dashboard"),
])
async def test_owner_started_turn_does_not_report_using_stale_parent_sender(
    monkeypatch, provenance,
):
    from app import fan_barrier
    from app.events import MessageProvenance
    from app.session import _is_owner_direct_message
    from app.session_state import AgentStatus

    session = _session()
    origin, senders, subtype = provenance
    owner_message = MessageProvenance(origin, senders, subtype=subtype)
    session._start_turn_state(
        owner_initiated=_is_owner_direct_message(owner_message),
    )
    session.status = AgentStatus.IDLE
    session._turn_logs = ["work completed"]
    monkeypatch.setattr(fan_barrier, "should_buffer", lambda *_args: False)

    session._turns.fire_auto_report()
    await asyncio.sleep(0)

    session.on_idle.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provenance", [
    ("agent", ("parent",), "direct_message"),
    ("background_task", ("job-1",), "completed"),
])
async def test_parented_task_and_background_job_turns_still_report(
    monkeypatch, provenance,
):
    from app import fan_barrier
    from app.events import MessageProvenance
    from app.session import _is_owner_direct_message
    from app.session_state import AgentStatus

    session = _session()
    origin, senders, subtype = provenance
    task_message = MessageProvenance(origin, senders, subtype=subtype)
    if origin == "background_task":
        from app.bg_jobs import BgJobManager

        session.last_task_sender = ""
        BgJobManager._restore_report_provenance(session)
    session._start_turn_state(
        owner_initiated=_is_owner_direct_message(task_message),
    )
    session.status = AgentStatus.IDLE
    session._turn_logs = ["work completed"]
    monkeypatch.setattr(fan_barrier, "should_buffer", lambda *_args: False)

    session._turns.fire_auto_report()
    await session._auto_report_task

    session.on_idle.assert_awaited_once()


@pytest.mark.asyncio
async def test_abnormal_end_still_reports_owner_started_turn(monkeypatch):
    from app import fan_barrier

    session = _session()
    session._owner_initiated_turn = True
    monkeypatch.setattr(fan_barrier, "should_buffer", lambda *_args: False)

    session._turns.report_abnormal_end("listener died")
    await session._auto_report_task

    session.on_idle.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,senders,subtype", [
    ("user", ("user",), "http_send"),
    ("unknown", ("dashboard",), "dashboard"),
])
async def test_owner_provenance_through_send_suppresses_parent_report(
    monkeypatch, origin, senders, subtype,
):
    from app.events import MessageProvenance

    session = _session()
    await _run_one_turn(
        session,
        MessageProvenance(origin, senders, subtype=subtype),
        monkeypatch,
    )

    session.on_idle.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,senders,subtype", [
    ("agent", ("parent",), "direct_message"),
    ("background_task", ("job-1",), "completed"),
])
async def test_parent_task_and_bg_job_provenance_through_send_still_report(
    monkeypatch, origin, senders, subtype,
):
    from app.events import MessageProvenance
    from app.bg_jobs import BgJobManager

    session = _session()
    if origin == "background_task":
        session.last_task_sender = ""
        BgJobManager._restore_report_provenance(session)
    await _run_one_turn(
        session,
        MessageProvenance(origin, senders, subtype=subtype),
        monkeypatch,
    )

    session.on_idle.assert_awaited_once()
