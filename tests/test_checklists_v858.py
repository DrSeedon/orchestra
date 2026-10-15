from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request


@pytest.fixture
def checklist_db(tmp_path, monkeypatch):
    from app import checklists, db

    path = tmp_path / "checklists.sqlite"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()
    checklists.ensure_schema()
    return db, checklists


def _insert_session(db, session_id: str, task_id: str, *, role="worker", is_orchestrator=False) -> None:
    db.save_session({
        "id": session_id, "name": session_id, "scope": "/v858", "cwd": "/v858",
        "model": "test-model", "system_prompt": "", "status": "running", "session_id": None,
        "cost_usd": 0.0, "worktree_path": "", "branch": "main", "base_branch": "main",
        "needs_switch": 0, "is_orchestrator": is_orchestrator, "color": "", "role": role,
        "parent_id": "", "parent_name": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "task_id": task_id,
    })


def test_checklist_counts_survive_end_of_turn(checklist_db, monkeypatch):
    from app.session import AgentSession, AgentStatus

    db, checklists = checklist_db
    _insert_session(db, "worker-checklist", "task-1")
    session = AgentSession(
        id="worker-checklist", name="worker", scope="/v858", cwd="/v858",
        status=AgentStatus.RUNNING, task_id="task-1",
    )
    session._persist = Mock()
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    turn_key = checklists.make_turn_key(session.id, 4)
    checklists.save_checklist(
        session.id, session.task_id, turn_key,
        items=["Inspect the code", "Write the change", "Check the UI", "Report"],
        completed=[0, 1], current=2,
    )
    session.progress_pct = 76
    session._turn_gen = 4

    session._turns.finish_turn_status()

    persisted = checklists.get_checklist(session.id, session.task_id)
    assert session.status == AgentStatus.IDLE
    assert session.progress_pct == 0
    assert persisted["completed"] == 2
    assert persisted["total"] == 4
    assert persisted["current"] == "Check the UI"


def test_summary_is_attached_by_session_and_current_task(checklist_db):
    db, checklists = checklist_db
    _insert_session(db, "worker", "task-1")
    checklists.save_checklist(
        "worker", "task-1", "turn-a",
        items=["A", "B", "C"], completed=[0], current=1,
    )
    summary = checklists.summaries_for_sessions([
        {"id": "worker", "task_id": "task-1"},
        {"id": "worker", "task_id": "task-2"},
    ])
    assert summary["worker"]["completed"] == 1
    assert summary["worker"]["total"] == 3
    assert summary["worker"]["current"] == "B"


def test_reminder_delay_flag_expiry_and_once_per_turn(checklist_db, monkeypatch):
    db, checklists = checklist_db
    from app.session import AgentSession, AgentStatus

    _insert_session(db, "worker-reminder", "task-1")

    assert checklists.reminders_enabled(datetime(2026, 10, 22, 23, 59, tzinfo=timezone.utc))
    assert not checklists.reminders_enabled(datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc))
    assert checklists.REMINDER_DELAY_SECONDS == 300
    monkeypatch.setenv(checklists.REMINDER_FLAG, "0")
    assert not checklists.reminders_enabled(datetime(2026, 10, 20, tzinfo=timezone.utc))
    monkeypatch.setenv(checklists.REMINDER_FLAG, "1")
    monkeypatch.setattr(checklists, "REMINDER_CUTOFF", date(2026, 10, 14))
    expired = AgentSession(
        id="worker-expired", name="worker", scope="/v858", cwd="/v858",
        status=AgentStatus.RUNNING, task_id="task-1",
    )
    expired.send = AsyncMock()
    expired._log = Mock()
    asyncio.run(expired._watch_checklist_reminder(1, "expired-turn"))
    expired.send.assert_not_awaited()

    monkeypatch.setattr(checklists, "REMINDER_CUTOFF", date(2026, 10, 22))
    monkeypatch.setattr(checklists, "REMINDER_DELAY_SECONDS", 0.02)

    session = AgentSession(
        id="worker-reminder", name="worker", scope="/v858", cwd="/v858",
        status=AgentStatus.RUNNING, task_id="task-1",
    )
    session._turn_gen = 7
    session.send = AsyncMock()
    session._log = Mock()
    turn_key = checklists.make_turn_key(session.id, 7)
    checklists.register_turn(session.id, session.task_id, 7, turn_key)

    async def fire_once():
        await session._watch_checklist_reminder(7, turn_key)
        await session._watch_checklist_reminder(7, turn_key)

    asyncio.run(fire_once())
    session.send.assert_awaited_once()
    logged = [call for call in session._log.call_args_list if call.args[0] == "checklist_reminder"]
    assert len(logged) == 1 and logged[0].kwargs["event_id"] == turn_key
    provenance = session.send.await_args.kwargs["provenance"]
    assert provenance.origin == "platform" and provenance.subtype == "checklist_reminder"


def test_update_after_reminder_is_counted_for_that_turn(checklist_db):
    db, checklists = checklist_db
    _insert_session(db, "worker", "task-1")
    turn_key = checklists.make_turn_key("worker", 2)
    checklists.register_turn("worker", "task-1", 2, turn_key)
    assert checklists.claim_reminder(turn_key)
    assert not checklists.claim_reminder(turn_key)
    checklists.save_checklist(
        "worker", "task-1", turn_key,
        items=["Plan", "Implement", "Verify"], completed=[0], current=1,
    )
    assert checklists.reminder_effect_counts() == {"reminders": 1, "followed_by_update": 1}


@pytest.mark.asyncio
async def test_checklist_update_restarts_the_five_minute_idle_window(checklist_db, monkeypatch):
    db, checklists = checklist_db
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr(checklists, "REMINDER_DELAY_SECONDS", 0.2)
    _insert_session(db, "worker-reset-timer", "task-1")
    session = AgentSession(
        id="worker-reset-timer", name="worker", scope="/v858", cwd="/v858",
        status=AgentStatus.RUNNING, task_id="task-1",
    )
    session._turn_gen = 9
    session.send = AsyncMock()
    session._log = Mock()
    turn_key = checklists.make_turn_key(session.id, 9)
    checklists.register_turn(session.id, session.task_id, 9, turn_key)
    task = asyncio.create_task(session._watch_checklist_reminder(9, turn_key))
    await asyncio.sleep(0.12)
    session._checklist_activity_event.set()
    await asyncio.sleep(0.12)
    session.send.assert_not_awaited()
    await asyncio.wait_for(task, timeout=0.5)
    session.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_turn_start_arms_and_turn_end_cancels_reminder(checklist_db, monkeypatch):
    db, checklists = checklist_db
    from app.session import AgentSession, AgentStatus

    _insert_session(db, "worker-lifecycle", "task-1")
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(checklists, "REMINDER_DELAY_SECONDS", 60)
    session = AgentSession(
        id="worker-lifecycle", name="worker", scope="/v858", cwd="/v858",
        status=AgentStatus.IDLE, task_id="task-1",
    )
    session._persist = Mock()

    session._start_turn_state()
    monitor = session._checklist_reminder_task
    assert monitor is not None and not monitor.done()
    assert session._checklist_turn_key

    session._turns.finish_turn_status()
    await asyncio.sleep(0)
    assert session.status == AgentStatus.IDLE
    assert monitor.cancelled() or monitor.done()


@pytest.mark.asyncio
async def test_checklist_route_binds_tool_to_its_worker_session(checklist_db, monkeypatch):
    db, _checklists = checklist_db
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes
    from app.session import AgentStatus

    _insert_session(db, "worker", "task-1")
    _insert_session(db, "orch", "", role="orchestrator", is_orchestrator=True)
    worker = SimpleNamespace(
        id="worker", name="worker", scope="/v858", loaded=True,
        status=AgentStatus.RUNNING, task_id="task-1", _turn_gen=3,
        _checklist_turn_key="worker:turn-3", _checklist_activity_event=asyncio.Event(),
        _log=Mock(),
    )
    monkeypatch.setattr(routes.manager, "sessions", {"worker": worker})

    def request_for(session_id):
        proof = issue_mcp_proof(session_id).encode()
        return Request({
            "type": "http", "method": "POST", "path": "/api/sessions/worker/checklist",
            "headers": [(b"x-orchestra-session-id", session_id.encode()),
                        (b"x-orchestra-mcp-proof", proof)],
        })

    accepted = await routes.update_session_checklist(
        "worker",
        routes.ChecklistUpdateRequest(items=["Inspect", "Implement"], completed=[0], current=1),
        request_for("worker"),
    )
    spoofed = await routes.update_session_checklist(
        "orch",
        routes.ChecklistUpdateRequest(items=["Inspect"], completed=[], current=0),
        request_for("worker"),
    )
    orchestrator = await routes.update_session_checklist(
        "orch",
        routes.ChecklistUpdateRequest(items=["Inspect"], completed=[], current=0),
        request_for("orch"),
    )

    assert accepted["completed"] == 1 and accepted["total"] == 2
    assert worker._checklist_activity_event.is_set()
    assert spoofed.status_code == 403
    assert orchestrator.status_code == 403


@pytest.mark.asyncio
async def test_session_list_receives_compact_checklist_count(checklist_db, monkeypatch):
    db, checklists = checklist_db
    from app.routes import sessions as routes
    _insert_session(db, "worker", "task-1")
    checklists.save_checklist(
        "worker", "task-1", "turn-list",
        items=["Inspect", "Implement", "Verify"], completed=[0, 1], current=2,
    )
    monkeypatch.setattr(routes.manager, "list_sessions", lambda _scope: [
        {"id": "worker", "name": "worker", "task_id": "task-1"},
    ])
    request = SimpleNamespace(headers={})

    response = await routes.list_sessions(request, "/v858")

    assert response.body
    import json
    assert json.loads(response.body)[0]["checklist_progress"] == {
        "completed": 2, "total": 3, "current": "Verify",
        "updated_at": checklists.get_checklist("worker", "task-1")["updated_at"],
    }
