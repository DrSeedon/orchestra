"""Regression oracle for deferred user input crossing the compact ack boundary."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.events import AgentEvent, MessageProvenance


PENDING_MESSAGE = "почини критический авто-компакт, затем проверь очередь"
SUMMARY = "TASK STATE\n- Compact summary.\n" + "x" * 240
USER_PROVENANCE = MessageProvenance(origin="user", senders=("user",))


class _SummaryBackend:
    def __init__(self, session):
        self.session = session

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def send(self, _message):
        return None

    async def events(self):
        yield AgentEvent("text", SUMMARY)
        await self.session.send(PENDING_MESSAGE, provenance=USER_PROVENANCE)
        yield AgentEvent(
            "turn_end",
            metadata={"session_id": "summary-session", "ok": True},
        )


@pytest.fixture
def session(tmp_path, monkeypatch):
    from app.session import AgentSession

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(
        "app.session._claude_subscription_limit_active", lambda: False,
    )
    instance = AgentSession(
        id="compact-pending-467",
        name="compact-pending-467",
        scope="/test",
        cwd=str(tmp_path),
        model="claude-opus-5[1m]",
        system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )
    instance._is_orchestrator = True
    instance.session_id = "pre-compact-session"
    instance._last_context = {
        "percentage": 95,
        "total_tokens": 950_000,
        "max_tokens": 1_000_000,
        "known": True,
    }
    instance._wake_durable_message_deliveries = MagicMock()
    return instance


@pytest.mark.asyncio
async def test_pending_user_input_waits_until_compact_ack_succeeds(
    session, monkeypatch,
):
    """A queued message must not turn the bounded ack into a real work turn."""
    summary_backend = _SummaryBackend(session)
    ack_backend = SimpleNamespace(
        sent=[],
        disconnect=MagicMock(),
    )

    async def ack_send(message):
        ack_backend.sent.append(message)

    async def ack_disconnect():
        return None

    ack_backend.send = ack_send
    ack_backend.disconnect = ack_disconnect

    async def ensure_backend(*, force_fresh=False, **_kwargs):
        assert force_fresh is True
        session._backend = ack_backend
        return ack_backend

    async def bounded_ack(waitable, *, timeout):
        waitable.close()
        assert timeout == 60
        if PENDING_MESSAGE in ack_backend.sent[-1]:
            raise asyncio.TimeoutError
        session.status = __import__("app.session", fromlist=["AgentStatus"]).AgentStatus.IDLE
        session.session_id = "fresh-session"

    spawned = []

    def capture_background(coroutine):
        spawned.append(coroutine)
        coroutine.close()

    monkeypatch.setattr(session, "_make_backend", MagicMock(return_value=summary_backend))
    monkeypatch.setattr(session, "_ensure_backend", ensure_backend)
    monkeypatch.setattr(session, "_spawn_bg", capture_background)
    monkeypatch.setattr("app.session.asyncio.wait_for", bounded_ack)
    monkeypatch.setattr(
        "app.session.get_logs",
        lambda *_args, **_kwargs: [
            {"type": "user_message", "content": PENDING_MESSAGE},
        ],
    )

    result = await session.compact()

    assert result["ok"] is True, (
        f"{result}; pending input leaked into ack="
        f"{PENDING_MESSAGE in ack_backend.sent[-1]}"
    )
    assert PENDING_MESSAGE not in ack_backend.sent[-1]
    assert session._pending_messages == [PENDING_MESSAGE]
    assert len(spawned) == 1
