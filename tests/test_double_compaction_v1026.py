"""Prevent stale context from compacting an already compacted native session."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events import AgentEvent
from app.manager import SessionManager
from app.session import AgentSession, AgentStatus
from app.usage_contract import AggregateUsage, TurnUsage, deferred_context


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_COMPACT_ENABLED", "1")
    monkeypatch.setenv("AGENTIC_COMPACT_ENABLED", "0")
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
    monkeypatch.setattr("app.session._compact_prompt", lambda *_: "summarize")
    monkeypatch.setattr("app.session._preserved_tail", lambda *_a, **_k: "")
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    s = AgentSession(
        id="compact-v1026", name="compact-v1026", scope=str(tmp_path), cwd=str(tmp_path),
        role="orchestrator", model="claude-opus-5-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc), session_id="old-native",
    )
    s.is_orchestrator = True
    # Use the same loader and legacy shape (no `known`) as restart recovery.
    row = s._to_db_dict()
    row.update(context_pct=95, context_tokens=945_985)
    s._last_context = SessionManager._hydrate_row(row)._last_context
    s._last_context["max_tokens"] = 1_000_000
    s.snapshots = []
    s._persist = lambda: s.snapshots.append(s._to_db_dict())
    s._drain_persist = AsyncMock()
    s._wake_durable_message_deliveries = MagicMock()
    s._hibernate.schedule = MagicMock()
    s._schedule_precompact_timer = MagicMock()
    s._cancel_precompact_timer = MagicMock()
    s._log = MagicMock()
    s.spawned = []

    def capture(coro):
        s.spawned.append(coro)

    s._spawn_bg = capture
    yield s
    for coro in s.spawned:
        coro.close()


def end_turn(s, *, tokens=104_899, calls=1):
    usage = TurnUsage(
        AggregateUsage.normalized(input_tokens=tokens, model_calls=calls),
        deferred_context(1_000_000, "claude_context_usage"),
    )
    s._handle_event(AgentEvent(
        "turn_end", metadata={
            "ok": True, "stop_reason": "end_turn", "num_turns": calls,
            "session_id": "fresh-native", "cost_usd": 0, **usage.metadata(),
        }, usage=usage,
    ))


async def compact(s, monkeypatch, *, tokens=104_899, calls=1, fail=False):
    async def summary_events():
        yield AgentEvent("text", "Retain task state")
        yield AgentEvent("turn_end", metadata={"ok": True, "session_id": "old-native"})

    summary = SimpleNamespace(
        connect=AsyncMock(), disconnect=AsyncMock(), send=AsyncMock(), events=summary_events,
    )

    async def ack_send(_):
        if fail:
            s._session_limit_hit = True
        end_turn(s, tokens=tokens, calls=calls)

    ack = SimpleNamespace(send=ack_send, disconnect=AsyncMock(), context_usage=AsyncMock(return_value=None))

    async def fresh_backend(**_):
        s._backend = ack
        return ack

    monkeypatch.setattr(s, "_make_backend", lambda: summary)
    monkeypatch.setattr(s, "_ensure_backend", fresh_backend)
    return await s.compact()


@pytest.mark.asyncio
@pytest.mark.parametrize("calls", [1, 3])
async def test_success_replaces_usage_before_release_and_restart(session, monkeypatch, calls):
    s = session
    released = []
    s._wake_durable_message_deliveries = lambda: released.append(dict(s._last_context))
    result = await compact(s, monkeypatch, tokens=104_899 * calls, calls=calls)

    assert result["ok"] is True
    assert result["pre_tokens"] == 945_985
    assert result["post_tokens"] == 104_899
    assert result["after_pct"] == 10
    assert released[-1]["total_tokens"] == 104_899
    assert s._last_context["percentage"] == 10
    assert s.snapshots[-1]["context_pct"] == 10
    assert s.snapshots[-1]["context_tokens"] == 104_899
    restored = SessionManager._hydrate_row(s.snapshots[-1])
    assert restored._last_context["percentage"] == 10
    assert restored._last_context["total_tokens"] == 104_899
    s._auto_compact = AsyncMock()
    end_turn(s, tokens=1)
    s._auto_compact.assert_not_called()
    finish = [json.loads(call.args[1]) for call in s._log.call_args_list
              if call.args[0] == "compact_event" and json.loads(call.args[1])["action"] == "finish"]
    assert len(finish) == 1 and finish[0]["after_pct"] == 10


@pytest.mark.asyncio
async def test_restored_high_usage_waits_for_new_reading_then_can_trigger(session):
    s = session
    s._auto_compact = AsyncMock()
    s._backend = SimpleNamespace(context_usage=AsyncMock(return_value=None))
    s.status = AgentStatus.RUNNING
    end_turn(s)
    s._auto_compact.assert_not_called()
    refresh = next(coro for coro in s.spawned if coro.cr_code.co_name == "_refresh_context_from_api")
    s.spawned.remove(refresh)
    await refresh
    s._auto_compact.assert_not_called()

    s._backend.context_usage.return_value = {
        "percentage": 95, "total_tokens": 951_000, "max_tokens": 1_000_000,
    }
    s._start_turn_state()
    end_turn(s)
    refresh = next(coro for coro in s.spawned if coro.cr_code.co_name == "_refresh_context_from_api")
    s.spawned.remove(refresh)
    await refresh
    s._auto_compact.assert_called_once_with(delay_seconds=0)


@pytest.mark.asyncio
async def test_missing_ack_usage_invalidates_old_snapshot(session, monkeypatch):
    result = await compact(session, monkeypatch, tokens=0)
    assert result["ok"] is True
    assert result["after_pct"] == 0
    assert session._last_context["known"] is False
    assert session.snapshots[-1]["context_tokens"] == 0
    assert session.snapshots[-1]["context_pct"] == 0


@pytest.mark.asyncio
async def test_failed_ack_keeps_original_snapshot(session, monkeypatch):
    result = await compact(session, monkeypatch, fail=True)
    assert result["ok"] is False
    assert session.session_id == "old-native"
    assert session._last_context["total_tokens"] == 945_985
    assert session._last_context["percentage"] == 95


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["backend", "session_id", "turn"])
async def test_refresh_from_previous_context_cannot_restore_high_usage(session, replacement):
    s = session
    entered = asyncio.Event()
    release = asyncio.Event()

    async def old_usage():
        entered.set()
        await release.wait()
        return {"percentage": 95, "total_tokens": 945_985, "max_tokens": 1_000_000}

    s._backend = SimpleNamespace(context_usage=old_usage)
    s._auto_compact = AsyncMock()
    task = asyncio.create_task(s._refresh_context_from_api(schedule_compaction_on_success=True))
    await asyncio.wait_for(entered.wait(), timeout=1)
    if replacement == "backend":
        s._backend = SimpleNamespace(context_usage=AsyncMock(return_value=None))
    elif replacement == "session_id":
        s.session_id = "fresh-native"
    else:
        s._turns.bump_turn_gen()
    s._last_context.update(percentage=10, total_tokens=104_899)
    release.set()
    await asyncio.wait_for(task, timeout=1)

    assert s._last_context["total_tokens"] == 104_899
    s._auto_compact.assert_not_called()
