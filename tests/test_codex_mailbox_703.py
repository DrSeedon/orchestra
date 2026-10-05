import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db, mailbox
from app.events import AgentEvent, MessageProvenance
from app.session import AgentSession, AgentStatus


@pytest.fixture
def codex_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "codex-mailbox.db")
    db.init_db()
    session = AgentSession(
        id="codex-mailbox-session",
        name="codex-mailbox",
        scope="/repo",
        cwd="/repo",
        backend_type="codex",
        created_at=datetime.now(timezone.utc),
    )
    session.status = AgentStatus.RUNNING
    session._log = MagicMock()
    session._persist = MagicMock()
    session._backend = MagicMock(send=AsyncMock())
    session._backend.active_turn_id = "turn-703"
    return session


@pytest.mark.asyncio
async def test_active_codex_message_is_steered_and_kept_as_backup(codex_session):
    session = codex_session

    await session.send(
        "urgent follow-up",
        provenance=MessageProvenance(origin="user", senders=("user",)),
    )

    pending = mailbox.pending(session.name, session.scope)
    assert [message["body"] for message in pending] == ["urgent follow-up"]
    session._backend.send.assert_awaited_once_with("urgent follow-up")
    assert pending[0]["provenance"].subtype == "codex_steer_backup"
    assert pending[0]["provenance"].ref == "turn-703"


@pytest.mark.asyncio
async def test_successful_turn_does_not_replay_steer_backup(codex_session, monkeypatch):
    session = codex_session
    import app.session_turns as turns

    origin = MessageProvenance(origin="user", senders=("user",))
    await session.send("urgent follow-up", provenance=origin)
    assert len(mailbox.pending(session.name, session.scope)) == 1

    session._cost.apply_turn_result = MagicMock(return_value=(True, "end_turn", 1))
    session._cost.update_context_from_turn = MagicMock(return_value=(True, ""))
    session._turn_start = 1
    session._last_context = {"percentage": 0}
    session._submit_db_write = MagicMock()
    session._cancel_precompact_timer = MagicMock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._turns.finish_turn_status = MagicMock()
    session._turns.after_turn_idle_actions = MagicMock()
    monkeypatch.setattr(turns, "_cached_quota_snapshot", lambda *_args: {"state": {}})

    session._turns.handle_turn_end(AgentEvent("turn_end", metadata={
        "ok": True, "stop_reason": "end_turn", "event_id": "turn-703",
        "num_turns": 1,
    }))

    assert mailbox.pending(session.name, session.scope) == []
    session._backend.send.assert_awaited_once_with("urgent follow-up")


@pytest.mark.asyncio
async def test_failed_codex_turn_replays_steer_backup_exactly_once(codex_session):
    session = codex_session
    await session.send(
        "urgent follow-up",
        provenance=MessageProvenance(origin="user", senders=("user",)),
    )
    session._backend.send.assert_awaited_once_with("urgent follow-up")

    session._turns.publish_turn_finished = MagicMock()
    session._turns.report_abnormal_end = MagicMock()
    session._hibernate.schedule = MagicMock()
    session._spawn_bg = lambda coroutine: asyncio.create_task(coroutine)
    session.send = AsyncMock()
    session.status = AgentStatus.RUNNING

    session._finish_failed_running_turn("Codex turn interrupted")
    await asyncio.sleep(0)
    session.send.assert_awaited_once()
    assert "urgent follow-up" in session.send.await_args.args[0]
    assert mailbox.pending(session.name, session.scope) == []
