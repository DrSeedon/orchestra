"""V-642: silent-turn signal to the parent; delivered-but-not-started marker for senders."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db, stall_signals
from app.session_hibernate import HibernateManager
from app.session_state import AgentStatus

DELIVERY_ID = "00000000-0000-4000-8000-000000000642"
SOURCE_ID = "src-642"


def _worker(**over):
    base = dict(
        id="w-642", name="worker-642", task_id="V-642", parent_id="orch-642",
        status=AgentStatus.RUNNING, _backend=object(), _last_msg_time=100.0,
        _last_event="tool_use Bash",
    )
    return SimpleNamespace(**{**base, **over})


@pytest.fixture
def notify(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(stall_signals, "_notify", mock)
    return mock


@pytest.mark.asyncio
async def test_silence_signals_parent_exactly_once_and_rearms_on_event(notify):
    worker = _worker()
    manager = HibernateManager(worker)
    limit = stall_signals.SILENCE_SIGNAL_SECONDS

    await manager._signal_silence_once(100.0 + limit - 1)
    notify.assert_not_awaited()

    await manager._signal_silence_once(100.0 + limit + 1)
    await manager._signal_silence_once(100.0 + limit + 61)
    assert notify.await_count == 1
    parent_id, text = notify.await_args.args[:2]
    assert parent_id == "orch-642"
    assert "worker-642" in text and "V-642" in text
    assert "20 min" in text and "tool_use Bash" in text

    # An event arrives: silence starts over, the next signal needs a fresh 20 minutes.
    worker._last_msg_time = 5000.0
    await manager._signal_silence_once(5000.0 + limit - 1)
    assert notify.await_count == 1
    await manager._signal_silence_once(5000.0 + limit + 1)
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_heartbeat_reaches_silence_signal_only_for_running_live_backend(
    notify, monkeypatch,
):
    import app.session_hibernate as module

    loop_now = asyncio.get_event_loop().time()

    async def one_pass(worker):
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        monkeypatch.setattr(
            module, "asyncio",
            SimpleNamespace(
                sleep=sleep,
                get_event_loop=asyncio.get_event_loop,
                CancelledError=asyncio.CancelledError,
            ),
        )
        try:
            await HibernateManager(worker).heartbeat_loop()
        except asyncio.CancelledError:
            pass

    common = dict(
        backend_type="claude", _listen_task=SimpleNamespace(done=lambda: False),
        _log=MagicMock(), _persist=MagicMock(), _pending_messages=[],
        _turns=MagicMock(), _last_msg_time=loop_now - 1300,
    )
    await one_pass(_worker(status=AgentStatus.IDLE, **common))
    notify.assert_not_awaited()
    await one_pass(_worker(**common))
    assert notify.await_count == 1


def _insert_submitted(source=SOURCE_ID):
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        connection.execute(
            """INSERT INTO message_deliveries (
                delivery_id, schema_version, source_session_id, source_principal,
                source_name, source_scope, source_task_id, target_session_id,
                target_name, target_scope, target_task_id, target_generation,
                message, rendered_message, wake, payload_hash, state,
                created_at, updated_at
            ) VALUES (?,2,?,'p','src','/s','','w-642','worker-642','/s','','g',
                      'm','m',1,'h','SUBMITTED',?,?)""",
            (DELIVERY_ID, source, now, now),
        )


@pytest.fixture
def delivery_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "stall-642.db")
    db.init_db()
    _insert_submitted()


def _status():
    from app.message_deliveries import get_message_delivery

    return get_message_delivery(DELIVERY_ID, SOURCE_ID)


@pytest.mark.asyncio
async def test_delivery_without_turn_start_is_stalled_and_sender_told(delivery_db, notify):
    worker = _worker(status=AgentStatus.IDLE)
    assert await stall_signals.watch_turn_start(worker, DELIVERY_ID, grace=0) is True

    receipt = _status()
    assert receipt["stalled"] is True
    assert receipt["delivery_state"] == "SUBMITTED"
    assert receipt["error"]["code"] == "TURN_NOT_STARTED"
    assert "idle" in receipt["error"]["message"]
    assert receipt["next_action"]["code"] == "TURN_NOT_STARTED"
    assert notify.await_count == 1
    assert notify.await_args.args[0] == SOURCE_ID
    assert DELIVERY_ID in notify.await_args.args[1]

    # A second look never re-marks or re-notifies.
    assert await stall_signals.watch_turn_start(worker, DELIVERY_ID, grace=0) is False
    assert notify.await_count == 1


@pytest.mark.asyncio
async def test_delivery_with_turn_start_is_not_stalled(delivery_db, notify):
    worker = _worker(_last_msg_time=10.0)
    task = asyncio.create_task(
        stall_signals.watch_turn_start(worker, DELIVERY_ID, grace=0.05)
    )
    await asyncio.sleep(0)
    worker._last_msg_time = 11.0  # first provider event of the new turn
    assert await task is False

    receipt = _status()
    assert "stalled" not in receipt and receipt["error"] is None
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_delivery_never_starts_the_stall_watch(monkeypatch):
    """A message parked behind compaction/a running turn is legitimate waiting."""
    from app.events import MessageProvenance
    from app.session import AgentSession

    watch = MagicMock()
    monkeypatch.setattr("app.session.watch_turn_start", watch)
    session = AgentSession(
        id="w-642", name="worker-642", scope="/s", cwd="/tmp", model="claude-sonnet-5-5[1m]",
        system_prompt="", created_at=datetime.now(timezone.utc),
    )
    session._compacting = True
    delivery = SimpleNamespace(
        allow_running=True, delivery_id=DELIVERY_ID, mark_submitted=AsyncMock(),
        before_submit=AsyncMock(),
    )
    await session.send(
        "hi", delivery=delivery,
        provenance=MessageProvenance(origin="agent", senders=("src",)),
    )
    watch.assert_not_called()
    delivery.mark_submitted.assert_not_awaited()


@pytest.mark.asyncio
async def test_idle_delivery_starts_the_stall_watch(monkeypatch):
    from app.events import MessageProvenance
    from app.session import AgentSession

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    watch = MagicMock(return_value=asyncio.sleep(0))
    monkeypatch.setattr("app.session.watch_turn_start", watch)
    session = AgentSession(
        id="w-642", name="worker-642", scope="/s", cwd="/tmp", model="claude-sonnet-5-5[1m]",
        system_prompt="", created_at=datetime.now(timezone.utc),
    )
    backend = SimpleNamespace(send=AsyncMock(), active_turn_id=None)
    session._ensure_backend = AsyncMock(return_value=backend)
    session._admit_turn = AsyncMock()
    delivery = SimpleNamespace(
        allow_running=True, delivery_id=DELIVERY_ID, mark_submitted=AsyncMock(),
        before_submit=AsyncMock(), history_user_message="hi",
    )
    await session.send(
        "hi", delivery=delivery,
        provenance=MessageProvenance(origin="agent", senders=("src",)),
    )
    watch.assert_called_once_with(session, DELIVERY_ID)
