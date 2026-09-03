"""Rollback coverage for pending input held across the compact ack boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.test_compact_pending_ack_467 import (
    PENDING_MESSAGE,
    _SummaryBackend,
    session,
)


def test_tail_excludes_only_the_deferred_copy_of_repeated_input(monkeypatch):
    from app.session import _preserved_tail

    monkeypatch.setattr(
        "app.session.get_logs",
        lambda *_args, **_kwargs: [
            {"type": "user_message", "content": PENDING_MESSAGE},
            {"type": "text", "content": "earlier answer"},
            {"type": "user_message", "content": PENDING_MESSAGE},
        ],
    )

    tail = _preserved_tail(
        "compact-pending-467",
        10_000,
        exclude_user_messages=(PENDING_MESSAGE,),
    )

    assert tail.count(f"USER: {PENDING_MESSAGE}") == 1
    assert "ASSISTANT: earlier answer" in tail


@pytest.mark.asyncio
@pytest.mark.parametrize("ack_times_out", [False, True])
async def test_compact_outcome_then_delivers_pending_input_once(
    session, monkeypatch, ack_times_out,
):
    from app.session import AgentStatus

    summary_backend = _SummaryBackend(session)
    ack_backend = SimpleNamespace(sent=[])
    delivery_backend = SimpleNamespace(sent=[])

    async def ack_send(message):
        ack_backend.sent.append(message)

    async def delivery_send(message):
        delivery_backend.sent.append(message)

    async def disconnect():
        return None

    ack_backend.send = ack_send
    ack_backend.disconnect = disconnect
    delivery_backend.send = delivery_send

    async def ensure_backend(*, force_fresh=False, **_kwargs):
        backend = ack_backend if force_fresh else delivery_backend
        session._backend = backend
        return backend

    async def finish_ack(waitable, *, timeout):
        waitable.close()
        assert timeout == 60
        assert PENDING_MESSAGE not in ack_backend.sent[-1]
        if ack_times_out:
            raise asyncio.TimeoutError
        session.status = AgentStatus.IDLE
        session.session_id = "fresh-session"

    spawned = []

    def capture_background(coroutine):
        spawned.append(coroutine)

    monkeypatch.setattr(session, "_make_backend", MagicMock(return_value=summary_backend))
    monkeypatch.setattr(session, "_ensure_backend", ensure_backend)
    monkeypatch.setattr(session, "_spawn_bg", capture_background)
    monkeypatch.setattr("app.session.asyncio.wait_for", finish_ack)
    monkeypatch.setattr("app.session.asyncio.sleep", AsyncMock())
    monkeypatch.setattr(
        "app.session.get_logs",
        lambda *_args, **_kwargs: [
            {"type": "user_message", "content": PENDING_MESSAGE},
        ],
    )

    result = await session.compact()

    assert result["ok"] is not ack_times_out
    if ack_times_out:
        assert result["error"] == "ack turn did not complete"
        assert session.session_id == "pre-compact-session"
    else:
        assert session.session_id == "fresh-session"
    assert session._pending_messages == [PENDING_MESSAGE]
    assert len(spawned) == 1

    await spawned.pop()

    assert delivery_backend.sent == [PENDING_MESSAGE]
    assert session._pending_messages == []
