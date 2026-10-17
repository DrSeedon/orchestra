"""V-919: a turn cut by a restart continues by itself after the restart."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from claude_agent_sdk import SystemMessage

from app.backend_claude import ClaudeBackend
from app.backend_protocol import AgentEvent
from app.events import MessageProvenance
from app.session import AgentSession

pytestmark = pytest.mark.usefixtures("no_real_exit_guard")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "orchestra-919.db")
    from app.db import init_db
    init_db()


def _save_row(cwd, *, row_id, name, session_id=None, status="running", parent_name="orch"):
    from app.db import save_session

    save_session({
        "id": row_id, "name": name, "scope": str(cwd), "cwd": str(cwd),
        "model": "claude-sonnet-5-5[1m]", "backend_type": "claude", "system_prompt": "",
        "status": status, "session_id": session_id, "cost_usd": 0.0,
        "worktree_path": None, "branch": None, "is_orchestrator": False,
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "role": "worker", "pipeline": "default", "color": "#818cf8",
        "parent_name": parent_name,
    })


def _signals() -> int:
    from app import db, turn_signals
    turn_signals.ensure_schema()
    with db._conn() as connection:
        return connection.execute("SELECT COUNT(*) FROM turn_signals").fetchone()[0]


def _manager(monkeypatch, *, fail=False):
    from app.manager import SessionManager

    manager = SessionManager()
    loaded, spawned = [], []

    async def load(row, *, recovery_handoff=None):
        if fail:
            raise RuntimeError("cannot load")
        session = SimpleNamespace(id=row["id"], name=row["name"])
        loaded.append(session)
        manager.sessions[session.id] = session
        return session

    monkeypatch.setattr(manager, "_load_from_db", load)
    monkeypatch.setattr(
        "app.manager.spawn_supervised",
        lambda awaitable, label: spawned.append(awaitable),
    )
    return manager, loaded, spawned


def test_claude_init_message_reports_session_id_before_turn_end():
    backend = ClaudeBackend(model="claude-sonnet-5-5[1m]", cwd="/tmp")

    events = backend._convert(SystemMessage(
        subtype="init", data={"type": "system", "subtype": "init", "session_id": "sid-919"},
    ))

    assert [e.metadata.get("session_id") for e in events] == ["sid-919"]
    assert backend.session_id == "sid-919"


def test_early_session_id_is_persisted_and_starts_a_fresh_cost_baseline():
    session = AgentSession(
        id="early-919", name="early-919", scope="/early-919", cwd="/tmp",
        model="claude-sonnet-5-5[1m]", created_at=datetime.now(timezone.utc),
    )
    session._persist = MagicMock()
    session._log = MagicMock()
    session._last_cost = 5.0

    session._handle_event(AgentEvent("status", "claude session=sid-919",
                                     metadata={"session_id": "sid-919"}))

    assert session.session_id == "sid-919"
    session._persist.assert_called()
    # Cumulative SDK cost of the new session must not be netted against the old session.
    session._cost.apply_turn_result({"session_id": "sid-919", "cost_usd": 1.0})
    assert session._turn_cost == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_first_turn_without_session_id_is_resumed_with_its_messages(
    isolated_db, tmp_path, monkeypatch,
):
    from app.db import add_log
    from app.manager import restart_notice_text

    row_id = "91900000-0000-4000-8000-000000000001"
    _save_row(tmp_path, row_id=row_id, name="first-turn-919")
    add_log(row_id, datetime.now(timezone.utc), "user_message", "TASK V-919 original body",
            provenance=MessageProvenance(origin="agent", senders=("orch",)))
    manager, loaded, spawned = _manager(monkeypatch)
    notice = AsyncMock()
    monkeypatch.setattr(manager, "_inject_restart_notice", notice)

    await manager.auto_resume_all()

    assert [s.id for s in loaded] == [row_id]
    await spawned[0]
    row = notice.await_args.args[1]
    assert "TASK V-919 original body" in restart_notice_text(row)
    assert _signals() == 0


@pytest.mark.asyncio
async def test_resumed_worker_does_not_report_a_failed_turn_to_its_parent(
    isolated_db, tmp_path, monkeypatch,
):
    _save_row(tmp_path, row_id="91900000-0000-4000-8000-000000000002",
              name="resumed-919", session_id="sid-resumed")
    manager, loaded, spawned = _manager(monkeypatch)
    monkeypatch.setattr(manager, "_inject_restart_notice", AsyncMock())

    await manager.auto_resume_all()

    assert len(loaded) == 1 and len(spawned) == 1
    await spawned[0]
    assert _signals() == 0


@pytest.mark.asyncio
async def test_worker_that_cannot_continue_is_reported_to_its_parent(
    isolated_db, tmp_path, monkeypatch,
):
    _save_row(tmp_path, row_id="91900000-0000-4000-8000-000000000003",
              name="broken-919", session_id="sid-broken")
    manager, _loaded, spawned = _manager(monkeypatch, fail=True)

    await manager.auto_resume_all()

    assert spawned == []
    assert _signals() == 1


@pytest.mark.asyncio
async def test_undeliverable_restart_notice_is_reported_to_the_parent(
    isolated_db, tmp_path, monkeypatch,
):
    from app import manager as manager_module

    row_id = "91900000-0000-4000-8000-000000000004"
    _save_row(tmp_path, row_id=row_id, name="notice-919", session_id="sid-notice")
    manager, _loaded, _spawned = _manager(monkeypatch)
    monkeypatch.setattr(manager, "send", AsyncMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr(manager_module.asyncio, "sleep", AsyncMock())
    from app.db import get_session_by_name
    row = get_session_by_name("notice-919", str(tmp_path))

    await manager._inject_restart_notice(SimpleNamespace(id=row_id, name="notice-919"), row)

    assert _signals() == 1
