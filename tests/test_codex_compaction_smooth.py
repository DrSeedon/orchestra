"""Incident 02.11 (seedon-orchestrator): Codex compacting ~785k tokens inside a turn.

A: Orchestra compacts a Codex thread between turns at 85% of Codex's own limit.
B: the owner's Stop does not replay the mailbox as a new turn; the next turn carries it.
C: compaction is visible (backend flag, session state, stream, Telegram notice).
No provider CLI, no live DB: every database is a tmp file.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db, mailbox
from app.backend_codex import CodexBackend, _configured_compaction_window
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus
from app.session_turns import (
    CODEX_PRE_LIMIT_COMPACT_COOLDOWN_SECONDS, TurnManager, _codex_pre_limit_threshold,
)

LIMIT = 400_000
THRESHOLD = LIMIT * 85 // 100  # 340_000
USER = MessageProvenance(origin="user", senders=("user",))


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "codex-smooth.db")
    db.init_db()


def _session(backend_type="codex", *, role="orchestrator", tokens=THRESHOLD):
    session = AgentSession(
        id=f"smooth-{backend_type}-{role}",
        name=f"smooth-{backend_type}",
        scope="/repo",
        cwd="/repo",
        role=role,
        backend_type=backend_type,
        model="gpt-6.1-sol" if backend_type == "codex" else "claude-sonnet-5-5[1m]",
        created_at=datetime.now(timezone.utc),
    )
    session.status = AgentStatus.IDLE
    session._log = MagicMock()
    session._persist = MagicMock()
    session._backend = MagicMock(send=AsyncMock(), active_turn_id=None)
    session._backend.auto_compact_token_limit = LIMIT
    session._last_context = {
        "known": True, "total_tokens": tokens, "max_tokens": 872_000,
        "percentage": round(tokens * 100 / 872_000),
    }
    return session


def _capture_spawn(session):
    spawned = []

    def capture(coroutine):
        spawned.append(coroutine)
        return MagicMock()

    session._spawn_bg = capture
    session._schedule_precompact_timer = MagicMock()
    session._cancel_precompact_timer = MagicMock()
    return spawned


def _close(spawned):
    for coroutine in spawned:
        coroutine.close()


def _statuses(session):
    return [c.args[1] for c in session._log.call_args_list if c.args[0] == "status"]


# ── A: compaction between turns before Codex's own limit ──

def test_codex_at_85_percent_of_its_limit_compacts_between_turns():
    session = _session()
    spawned = _capture_spawn(session)
    # The generic critical threshold (95% of the window) is far above 39%.
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])

    assert session._overflow_compact_scheduled is True
    assert [c.__qualname__ for c in spawned] == [
        "TurnManager._run_codex_pre_limit_compact",
    ]
    line = next(s for s in _statuses(session) if s.startswith("codex pre-limit compact:"))
    assert f"{THRESHOLD} tokens" in line and f"limit {LIMIT}" in line
    _close(spawned)


def test_codex_below_85_percent_does_not_compact():
    session = _session(tokens=THRESHOLD - 1)
    spawned = _capture_spawn(session)
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])

    assert spawned == []
    assert session._overflow_compact_scheduled is False
    session._schedule_precompact_timer.assert_called_once()


def test_codex_default_limit_is_90_percent_of_window_when_config_has_none(tmp_path):
    backend = CodexBackend(model="gpt-6.1-sol", cwd="/tmp")
    backend._model_context_window = 872_000
    assert backend.auto_compact_token_limit == 784_800
    backend._loaded_auto_compact_limit = 400_000
    assert backend.auto_compact_token_limit == 400_000
    # A configured value above Codex's own default is never trusted past it.
    backend._loaded_auto_compact_limit = 900_000
    assert backend.auto_compact_token_limit == 784_800
    # The runtime reports the effective (95%) window; the configured raw window is the
    # base of Codex's default, so the incident's 784800 of 872000 is not cut to 745560.
    backend._model_context_window = 828_400
    backend._loaded_auto_compact_limit = 784_800
    backend._loaded_context_window = 872_000
    assert backend.auto_compact_token_limit == 784_800
    backend._loaded_context_window = None
    assert backend.auto_compact_token_limit == 745_560

    config = tmp_path / "config.toml"
    config.write_text(
        'model = "x"\nmodel_auto_compact_token_limit = 400000\nmodel_context_window = 872000\n'
    )
    assert _configured_compaction_window(config) == (400_000, 872_000)
    config.write_text('model = "x"\nmodel_context_window = "big"\n')
    assert _configured_compaction_window(config) == (None, None)
    assert _configured_compaction_window(tmp_path / "missing.toml") == (None, None)


@pytest.mark.asyncio
async def test_connect_remembers_the_limit_of_the_loaded_managed_config(tmp_path, monkeypatch):
    import app.backend_codex as module

    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", tmp_path / "managed")
    monkeypatch.setattr(module, "_base_codex_home", lambda: tmp_path / "base")
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "config.toml").write_text(
        "model_auto_compact_token_limit = 400000\nmodel_context_window = 872000\n",
    )
    backend = CodexBackend(model="gpt-6.1-sol", cwd=str(tmp_path), mcp_servers={
        "orchestra": {"command": "python", "env": {"ORCHESTRA_SESSION_ID": "smooth-home"}},
    })
    backend._connect_unlocked = AsyncMock()
    backend._model_context_window = 872_000

    await backend.connect()

    assert backend._loaded_auto_compact_limit == 400_000
    assert backend._loaded_context_window == 872_000
    assert backend.auto_compact_token_limit == 400_000


def test_claude_is_unchanged_by_the_codex_rule():
    session = _session("claude", tokens=THRESHOLD)
    spawned = _capture_spawn(session)
    assert _codex_pre_limit_threshold(session) is None
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])

    assert spawned == []
    assert session._overflow_compact_scheduled is False
    assert not any("pre-limit" in s for s in _statuses(session))


@pytest.mark.parametrize("busy", ["_compacting", "_overflow_compact_scheduled"])
def test_no_second_compaction_while_one_runs(busy):
    session = _session()
    setattr(session, busy, True)
    spawned = _capture_spawn(session)
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])

    assert spawned == []
    session._schedule_precompact_timer.assert_not_called()


def test_no_compaction_after_the_owners_stop():
    session = _session()
    session._manually_interrupted = True
    spawned = _capture_spawn(session)
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])
    assert spawned == []
    assert session._overflow_compact_scheduled is False


@pytest.mark.parametrize("arm", ["kill_switch", "unknown_context", "running_turn"])
def test_pre_limit_compaction_respects_its_guards(monkeypatch, arm):
    session = _session(tokens=THRESHOLD + 50_000)
    if arm == "kill_switch":
        monkeypatch.setenv("AUTO_COMPACT_ENABLED", "0")
    elif arm == "unknown_context":
        session._last_context["known"] = False
    else:
        # A late context refresh can land after the next turn already started.
        session.status = AgentStatus.RUNNING
    spawned = _capture_spawn(session)
    TurnManager(session).schedule_context_compaction(40)

    assert not any("pre_limit" in c.__qualname__ for c in spawned)
    assert session._overflow_compact_scheduled is False
    assert not any("codex pre-limit compact" in s for s in _statuses(session))
    _close(spawned)


def test_orchestrator_outside_the_night_window_compacts():
    session = _session(role="orchestrator")
    session._auto_compact_window_state = lambda now_utc=None: {
        "allowed": False, "local_time": "14:00", "window": "02:00-06:00",
        "timezone": "Asia/Krasnoyarsk",
    }
    spawned = _capture_spawn(session)
    # Control arm: the generic rule would be blocked by the window for this session.
    assert session._auto_compact_window_blocked(50, log_status=False) is True
    TurnManager(session).schedule_context_compaction(session._last_context["percentage"])

    assert session._overflow_compact_scheduled is True
    assert len(spawned) == 1
    _close(spawned)


@pytest.mark.asyncio
async def test_messages_arriving_during_the_compaction_are_queued(tmp_db):
    session = _session()
    spawned = _capture_spawn(session)
    turns = TurnManager(session)
    session._turns = turns
    turns.schedule_context_compaction(session._last_context["percentage"])
    run = spawned.pop()

    await session.send("owner during compaction", provenance=USER)

    assert session._pending_messages == ["owner during compaction"]
    session._backend.send.assert_not_awaited()
    assert any("message queued (compact in progress" in s for s in _statuses(session))

    async def compacted():
        session._last_context["total_tokens"] = 20_000
        return {"ok": True, "mode": "native"}

    session.compact = compacted
    session._flush_pending = MagicMock(side_effect=lambda: asyncio.sleep(0))
    await run
    assert session._overflow_compact_scheduled is False
    assert session._codex_pre_limit_retry_at == 0.0
    session._flush_pending.assert_called_once()
    _close(spawned)


@pytest.mark.asyncio
@pytest.mark.parametrize("result, after", [
    ({"ok": False, "mode": "native", "error": "timeout"}, 20_000),
    ({"ok": True, "mode": "native"}, THRESHOLD + 5),  # done, but did not help
])
async def test_failed_compaction_cools_down_before_the_next_attempt(result, after):
    session = _session()
    spawned = _capture_spawn(session)
    turns = TurnManager(session)

    async def compact():
        session._last_context["total_tokens"] = after
        return result

    session.compact = compact
    turns.schedule_context_compaction(40)
    await spawned.pop()
    assert session._codex_pre_limit_retry_at > time.monotonic() + (
        CODEX_PRE_LIMIT_COMPACT_COOLDOWN_SECONDS - 60
    )

    session._last_context["total_tokens"] = THRESHOLD + 10
    turns.schedule_context_compaction(40)
    turns.schedule_context_compaction(40)
    assert spawned == []
    assert session._overflow_compact_scheduled is False
    # One line per cooldown, not one per turn end.
    assert sum("pre-limit compact postponed" in s for s in _statuses(session)) == 1

    # After the cooldown the next turn end tries again.
    session._codex_pre_limit_retry_at = time.monotonic() - 1
    turns.schedule_context_compaction(40)
    assert len(spawned) == 1
    _close(spawned)


@pytest.mark.asyncio
@pytest.mark.parametrize("tokens", [THRESHOLD, THRESHOLD - 1])
async def test_new_message_after_stop_compacts_before_its_turn(tmp_db, tokens):
    session = _session(tokens=tokens)
    spawned = _capture_spawn(session)
    session._manually_interrupted = True
    # The turn end of the owner's Stop starts nothing by itself.
    session._turns.schedule_context_compaction(40)
    assert not any("pre_limit" in c.__qualname__ for c in spawned)

    backend = session._backend
    backend.active_turn_id = "turn-next"
    session._ensure_backend = AsyncMock(return_value=backend)
    session._turn_event_loop = _parked_listener
    session._notify_scope_running = AsyncMock()
    await session.send("owner after stop", provenance=USER)

    if tokens >= THRESHOLD:
        # Codex would compact inside this turn: compact first, the message waits.
        assert [c.__qualname__ for c in spawned if "pre_limit" in c.__qualname__] == [
            "TurnManager._run_codex_pre_limit_compact",
        ]
        assert session._pending_messages == ["owner after stop"]
        backend.send.assert_not_awaited()
        assert any("compacting before this message" in s for s in _statuses(session))
    else:
        assert not any("pre_limit" in c.__qualname__ for c in spawned)
        assert backend.send.await_args.args[0] == "owner after stop"
        session._listen_task.cancel()
    _close(spawned)


@pytest.mark.asyncio
async def test_refused_start_still_wakes_durable_deliveries():
    session = _session()
    spawned = _capture_spawn(session)
    session._wake_durable_message_deliveries = MagicMock()

    async def refused():
        return {"ok": False, "error": "compaction start cancelled by stop"}

    session.compact = refused
    TurnManager(session).schedule_context_compaction(40)
    await spawned.pop()
    session._wake_durable_message_deliveries.assert_called_once()


@pytest.mark.asyncio
async def test_refused_start_does_not_cool_down():
    session = _session()
    spawned = _capture_spawn(session)

    async def refused():
        return {"ok": False, "error": "cannot compact while agent is running"}

    session.compact = refused
    TurnManager(session).schedule_context_compaction(40)
    await spawned.pop()
    assert session._codex_pre_limit_retry_at == 0.0
    assert session._overflow_compact_scheduled is False


# ── B: Stop really stops ──

def _backup(session, body, ref="turn-stopped"):
    return mailbox.enqueue(
        recipient=session.name, scope=session.scope, sender="user", body=body,
        provenance=MessageProvenance(
            origin="user", senders=("user",), subtype="codex_steer_backup", ref=ref,
        ),
    )


def _idle_tail_doubles(session):
    spawned = _capture_spawn(session)
    session._notify_scope_idle = MagicMock(side_effect=lambda: asyncio.sleep(0))
    session._hibernate.schedule = MagicMock()
    session._turns.fire_auto_report = MagicMock()
    return spawned


def test_manual_stop_does_not_start_a_new_turn_from_the_mailbox(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "first steer")
    _backup(session, "second steer")
    spawned = _idle_tail_doubles(session)
    session._manually_interrupted = True

    session._turns.after_turn_idle_actions(1, allow_precompact=False)

    assert not any(c.__qualname__ == "TurnManager._deliver_mailbox" for c in spawned)
    rows = mailbox.pending(session.name, session.scope)
    assert [r["body"] for r in rows] == ["first steer", "second steer"]
    assert all(r["claimed_at"] is None for r in rows)
    assert session._mailbox_held_after_stop is True
    assert any("mailbox: 2 held after Stop" in s for s in _statuses(session))
    session._hibernate.schedule.assert_called_once()
    _close(spawned)


def test_non_manual_interrupted_turn_keeps_todays_replay(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "steer of a cut turn")
    spawned = _idle_tail_doubles(session)

    session._turns.after_turn_idle_actions(1, allow_precompact=False)

    assert [c.__qualname__ for c in spawned if "mailbox" in c.__qualname__] == [
        "TurnManager._deliver_mailbox",
    ]
    assert session._mailbox_held_after_stop is False
    assert any("продолжаю ход вместо пробуждения" in s for s in _statuses(session))
    _close(spawned)


def test_claude_stop_keeps_todays_mailbox_continuation(tmp_db):
    session = _session("claude", tokens=1000)
    mailbox.enqueue(
        recipient=session.name, scope=session.scope, sender="peer", body="after turn",
        provenance=MessageProvenance(origin="agent", senders=("peer",)),
    )
    spawned = _idle_tail_doubles(session)
    session._manually_interrupted = True

    session._turns.after_turn_idle_actions(1, allow_precompact=False)

    assert any(c.__qualname__ == "TurnManager._deliver_mailbox" for c in spawned)
    _close(spawned)


def test_unacknowledged_stop_does_not_replay_either(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "steer")
    spawned = _idle_tail_doubles(session)
    session._turns.publish_turn_finished = MagicMock()
    session._turns.report_abnormal_end = MagicMock()
    session._manually_interrupted = True
    session.status = AgentStatus.RUNNING

    session._finish_failed_running_turn("interrupt was not acknowledged; backend disconnected")

    assert not any("mailbox" in c.__qualname__ for c in spawned)
    assert len(mailbox.pending(session.name, session.scope)) == 1
    _close(spawned)


async def _parked_listener():
    await asyncio.Event().wait()


async def _send_new_turn(session, text):
    backend = session._backend
    backend.active_turn_id = "turn-next"
    session._ensure_backend = AsyncMock(return_value=backend)
    session._turn_event_loop = _parked_listener
    session._notify_scope_running = AsyncMock()
    await session.send(text, provenance=USER)
    session._listen_task.cancel()


@pytest.mark.asyncio
async def test_next_message_delivers_held_steers_once_in_order(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "first steer")
    _backup(session, "second steer")
    spawned = _idle_tail_doubles(session)
    session._manually_interrupted = True
    session._turns.after_turn_idle_actions(1, allow_precompact=False)
    _close(spawned)

    await _send_new_turn(session, "owner after stop")

    sent = session._backend.send.await_args.args[0]
    assert sent.index("first steer") < sent.index("second steer") < sent.index("owner after stop")
    assert mailbox.pending(session.name, session.scope) == []
    assert session._mailbox_held_after_stop is False
    # The chat already shows the steers; the new turn logs only the new message.
    user_rows = [c.args[1] for c in session._log.call_args_list if c.args[0] == "user_message"]
    assert user_rows == ["owner after stop"]

    # Exactly once: the following turn carries nothing from the mailbox.
    session.status = AgentStatus.IDLE
    session._backend.send.reset_mock()
    await _send_new_turn(session, "later message")
    assert session._backend.send.await_args.args[0] == "later message"


@pytest.mark.asyncio
async def test_failed_submit_keeps_held_steers_for_the_turn_after(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "held steer")
    session._mailbox_held_after_stop = True
    session._backend.send = AsyncMock(side_effect=RuntimeError("provider down"))
    session._turns.publish_turn_finished = MagicMock()

    with pytest.raises(RuntimeError):
        await _send_new_turn(session, "owner after stop")

    rows = mailbox.pending(session.name, session.scope)
    assert [r["body"] for r in rows] == ["held steer"]
    assert rows[0]["claimed_at"] is None
    assert session._mailbox_held_after_stop is True


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped", [True, False])
async def test_deferred_mailbox_waiter_does_not_start_a_turn_after_stop(tmp_db, stopped):
    session = _session(tokens=1000)
    _backup(session, "deferred during a compaction")
    session._manually_interrupted = stopped
    session._turns._deliver_mailbox = AsyncMock()

    await session._turns._deliver_mailbox_when_free()

    rows = mailbox.pending(session.name, session.scope)
    if stopped:
        session._turns._deliver_mailbox.assert_not_awaited()
        assert [r["claimed_at"] for r in rows] == [None]
    else:
        session._turns._deliver_mailbox.assert_awaited_once()


@pytest.mark.asyncio
async def test_queued_flush_delivers_held_steers_once_in_order(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "first steer")
    _backup(session, "second steer")
    session._mailbox_held_after_stop = True
    session._pending_messages = ["queued during compaction"]
    backend = session._backend
    backend.active_turn_id = "turn-flush"
    session._ensure_backend = AsyncMock(return_value=backend)
    session._turn_event_loop = _parked_listener

    await session._flush_pending()
    session._listen_task.cancel()

    sent = backend.send.await_args.args[0]
    assert sent.count("first steer") == 1
    assert (sent.index("first steer") < sent.index("second steer")
            < sent.index("queued during compaction"))
    assert mailbox.pending(session.name, session.scope) == []
    assert session._mailbox_held_after_stop is False


@pytest.mark.asyncio
async def test_failed_flush_keeps_held_steers_for_the_turn_after(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "held steer")
    session._mailbox_held_after_stop = True
    session._pending_messages = ["queued during compaction"]
    session._backend.send = AsyncMock(side_effect=RuntimeError("provider down"))
    session._ensure_backend = AsyncMock(return_value=session._backend)
    session._turns.publish_turn_finished = MagicMock()

    await session._flush_pending()

    rows = mailbox.pending(session.name, session.scope)
    assert [r["body"] for r in rows] == ["held steer"]
    assert rows[0]["claimed_at"] is None
    assert session._mailbox_held_after_stop is True
    assert session._pending_messages == ["queued during compaction"]


@pytest.mark.asyncio
async def test_new_turn_that_fails_before_submission_releases_held_steers(tmp_db):
    session = _session(tokens=1000)
    _backup(session, "held steer")
    session._mailbox_held_after_stop = True
    session._attach_pending_facts = MagicMock(side_effect=RuntimeError("facts store down"))

    with pytest.raises(RuntimeError):
        await _send_new_turn(session, "owner after stop")

    rows = mailbox.pending(session.name, session.scope)
    assert [r["claimed_at"] for r in rows] == [None]
    assert session._mailbox_held_after_stop is True


@pytest.mark.asyncio
async def test_receipt_failure_after_the_provider_took_the_turn_acknowledges_held_steers(tmp_db):
    from types import SimpleNamespace

    session = _session(tokens=1000)
    _backup(session, "held steer")
    session._mailbox_held_after_stop = True
    session._turns.publish_turn_finished = MagicMock()
    delivery = SimpleNamespace(
        allow_running=False, history_user_message=None, delivery_id="d-held",
        before_submit=AsyncMock(), mark_unknown=AsyncMock(),
        mark_submitted=AsyncMock(side_effect=RuntimeError("receipt store down")),
    )
    backend = session._backend
    backend.active_turn_id = "turn-next"
    session._ensure_backend = AsyncMock(return_value=backend)
    session._turn_event_loop = _parked_listener
    session._notify_scope_running = AsyncMock()

    with pytest.raises(RuntimeError):
        await session.send("owner after stop", provenance=USER, delivery=delivery)

    assert "held steer" in backend.send.await_args.args[0]
    # The text is in the provider's turn: re-sending it would duplicate it.
    assert mailbox.pending(session.name, session.scope) == []
    assert session._mailbox_held_after_stop is False


# ── C: visible compaction ──

def _turn_backend():
    backend = CodexBackend(model="gpt-6.1-sol", cwd="/tmp")
    backend._active_turn_id = "turn-1"
    return backend


def _item(method, item_type="contextCompaction"):
    return {"method": method, "params": {
        "threadId": "thread", "turnId": "turn-1", "item": {"id": "c1", "type": item_type},
    }}


@pytest.mark.parametrize("finish", [
    _item("item/completed"),
    {"method": "context/compacted", "params": {"threadId": "thread", "turnId": "turn-1"}},
    {"method": "turn/completed", "params": {
        "threadId": "thread", "turn": {"id": "turn-1", "status": "interrupted"}}},
    {"method": "error", "params": {
        "threadId": "thread", "turnId": "turn-1", "willRetry": False,
        "error": {"message": "boom"}}},
])
def test_in_turn_compaction_flag_set_and_cleared(finish):
    backend = _turn_backend()
    assert backend.turn_compaction_started_at is None
    before = time.time()
    backend._convert_notification(_item("item/started"))
    assert before <= backend.turn_compaction_started_at <= time.time()

    backend._convert_notification(finish)
    assert backend._turn_compaction is None
    assert backend.turn_compaction_started_at is None


def test_second_compaction_item_keeps_the_bar_until_the_last_completes():
    backend = _turn_backend()
    backend._convert_notification(_item("item/started"))
    first = backend.turn_compaction_started_at
    second = _item("item/started")
    second["params"]["item"]["id"] = "c2"
    backend._convert_notification(second)
    assert backend.turn_compaction_started_at == first  # the clock does not restart

    backend._convert_notification(_item("item/completed"))  # c1
    assert backend.turn_compaction_started_at == first
    done = _item("item/completed")
    done["params"]["item"]["id"] = "c2"
    backend._convert_notification(done)
    assert backend.turn_compaction_started_at is None


def test_retrying_error_keeps_the_compaction_visible():
    backend = _turn_backend()
    backend._convert_notification(_item("item/started"))
    backend._convert_notification({"method": "error", "params": {
        "threadId": "thread", "turnId": "turn-1", "willRetry": True,
        "error": {"message": "reconnecting"}}})
    assert backend.turn_compaction_started_at is not None


@pytest.mark.asyncio
async def test_disconnect_and_a_new_turn_never_inherit_the_flag():
    backend = _turn_backend()
    backend._convert_notification(_item("item/started"))
    backend._active_turn_id = "turn-2"  # a stale flag of another turn is not shown
    assert backend.turn_compaction_started_at is None

    backend._active_turn_id = "turn-1"
    backend.teardown_owned_pipes = AsyncMock()
    await backend._finalize_disconnect()
    assert backend._turn_compaction is None


def test_session_exposes_compaction_state_to_the_dashboard():
    session = _session()
    assert session.compaction_state() is None
    assert session.to_dict()["compaction"] is None

    session.status = AgentStatus.RUNNING
    session._backend.turn_compaction_started_at = 1700000000.0
    assert session.compaction_state() == {"kind": "codex_turn", "started_at": 1700000000.0}
    assert session.to_dict()["compaction"]["kind"] == "codex_turn"

    session.status = AgentStatus.IDLE  # turn over: the flag cannot outlive it
    assert session.compaction_state() is None

    session._compacting = True
    session._compaction_started_at = 1700000100.0
    assert session.compaction_state() == {"kind": "orchestra", "started_at": 1700000100.0}

    claude = _session("claude")
    claude._compacting = True
    assert claude.compaction_state() is None


@pytest.mark.asyncio
async def test_native_compaction_permit_records_its_start():
    session = _session()
    before = time.time()
    await session._compaction_permit(reserve=True)
    assert session._compacting is True
    assert before <= session.compaction_state()["started_at"] <= time.time()


@pytest.mark.asyncio
async def test_stream_events_carry_the_compaction_state(tmp_db, monkeypatch):
    from app.routes import sessions as routes

    session = _session()
    session.status = AgentStatus.RUNNING
    session._backend.turn_compaction_started_at = 1700000000.0
    db.save_session({
        "id": session.id, "name": session.name, "scope": session.scope, "cwd": "/repo",
        "model": session.model, "system_prompt": "", "status": "running",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "", "is_orchestrator": True, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "",
    })
    monkeypatch.setattr(routes.manager, "get_session_id", lambda *_a: session.id)
    monkeypatch.setattr(routes.manager, "get", lambda _sid: session)
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=True)

    response = await routes.stream_session_logs(session.name, session.scope, request)
    first = await response.body_iterator.__anext__()
    payload = json.loads(first.removeprefix("data: ").strip())
    assert payload["agent_status"] == "running"
    assert payload["compaction"] == {"kind": "codex_turn", "started_at": 1700000000.0}
    await response.body_iterator.aclose()


class _Msg:
    def __init__(self):
        self.chat = type("Chat", (), {"id": -100})()
        self.message_thread_id = 7


@pytest.mark.asyncio
@pytest.mark.parametrize("compacting", [True, False])
async def test_telegram_user_is_told_about_compaction_once(monkeypatch, compacting):
    import app.main  # noqa: F401  (mutating_admission_open)
    import app.tg_bridge as tg

    session = _session()
    session.compaction_state = lambda: (
        {"kind": "codex_turn", "started_at": 1.0} if compacting else None
    )
    manager = MagicMock(get=lambda _sid: session, send=AsyncMock())
    sent = []

    async def fake_send(chat_id, text, thread_id=None, **_kw):
        sent.append((chat_id, text, thread_id))

    monkeypatch.setattr(tg, "_manager", manager, raising=False)
    monkeypatch.setattr(tg, "bot", object(), raising=False)
    monkeypatch.setattr(tg, "_tg_send_safe", fake_send)
    monkeypatch.setattr("app.main.mutating_admission_open", lambda: True)

    await tg._flush_batch(session.id, [(_Msg(), "привет", None)])

    manager.send.assert_awaited_once()
    if compacting:
        assert len(sent) == 1 and "сжимает контекст" in sent[0][1] and sent[0][2] == 7
    else:
        assert sent == []
