"""V-995: a send that would overflow the window compacts first; Claude re-decides after refresh."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.events import MessageProvenance
from app.session_turns import injection_overflows_context

USER = MessageProvenance(origin="user", senders=("user",))
PROMPT = "p" * 95_000  # the incident: 95K chars of refreshed prompt prepended to a short message


@pytest.fixture
def session(tmp_path, monkeypatch):
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setenv("AUTO_COMPACT_ENABLED", "1")
    s = AgentSession(
        id="overflow-995", name="overflow-995", scope="/test", cwd=str(tmp_path),
        model="claude-opus-5-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )
    s.backend_type = "claude"
    s.session_id = "resumed"
    s.status = AgentStatus.IDLE
    s._current_prompt = PROMPT
    s._last_context = {
        "percentage": 93, "total_tokens": 934_259, "max_tokens": 1_000_000, "known": True,
    }
    spawned = []

    def capture(coroutine):
        spawned.append(coroutine)
        coroutine.close()

    s._spawn_bg = capture
    s.spawned = spawned
    return s


def test_incident_numbers_overflow_but_small_context_does_not(session):
    # 934K live + 95K-char prompt + short message used to be sent as-is and got
    # "Prompt is too long"; the same message at 60% is fine.
    assert injection_overflows_context(session, len(PROMPT) + 40)
    session._last_context["total_tokens"] = 600_000
    assert not injection_overflows_context(session, len(PROMPT) + 40)


def test_unknown_context_never_blocks(session):
    session._last_context["known"] = False
    assert not injection_overflows_context(session, len(PROMPT))


@pytest.mark.asyncio
async def test_send_queues_message_and_compacts_instead_of_sending(session):
    backend = MagicMock()
    session._ensure_backend = MagicMock(side_effect=AssertionError("must not reach the backend"))

    await session.send("Скинь разбор платформ", provenance=USER)

    assert session._pending_messages == ["Скинь разбор платформ"]
    assert session._overflow_compact_scheduled is True
    assert len(session.spawned) == 1  # the compaction
    backend.send.assert_not_called()


@pytest.mark.asyncio
async def test_second_message_during_scheduled_compaction_is_queued_too(session):
    await session.send("first", provenance=USER)
    await session.send("second", provenance=USER)

    assert session._pending_messages == ["first", "second"]
    assert len(session.spawned) == 1  # no second compaction


@pytest.mark.asyncio
async def test_guard_does_not_loop_when_compaction_did_not_shrink_context(session):
    session._overflow_guard_tokens = 934_259  # previous guard compaction left it unchanged
    session._ensure_backend = MagicMock(side_effect=RuntimeError("reached backend"))

    with pytest.raises(RuntimeError, match="reached backend"):
        await session.send("again", provenance=USER)

    assert session._pending_messages == []
    assert session._overflow_compact_scheduled is False


@pytest.mark.asyncio
async def test_turn_end_redecides_on_refreshed_context_for_deferred_claude(session, monkeypatch):
    """Claude's context is measured by the refresh, so it must re-run the compaction decision."""
    from app.events import AgentEvent
    from app.session import AgentStatus
    from app.usage_contract import AggregateUsage, TurnUsage, deferred_context

    flags = []

    def refresh(*, schedule_compaction_on_success):
        flags.append(schedule_compaction_on_success)

        async def done():
            return None

        return done()

    session.status = AgentStatus.RUNNING
    session._refresh_context_from_api = refresh
    session._schedule_precompact_timer = MagicMock()
    session._hibernate.schedule = MagicMock()
    session._log = MagicMock()
    usage = TurnUsage(
        AggregateUsage.normalized(input_tokens=10_000),
        deferred_context(1_000_000, "claude_context_usage"),
    )
    session._turns.handle_turn_end(AgentEvent(
        "turn_end",
        metadata={"ok": True, "stop_reason": "end_turn", "num_turns": 1, "cost_usd": 0,
                  **usage.metadata()},
        usage=usage,
    ))

    assert flags == [True]
