"""Frozen RED behavior oracles for #433 T2: all six writer seams."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


def _provenance(seam: str, *, origin: str = "agent", subtype: str = "test"):
    import app.events as events
    provenance_type = getattr(events, "MessageProvenance", None)
    assert provenance_type is not None, (
        f"#433 T2 missing writer behavior at distinct seam: {seam} has no B1 value"
    )
    return provenance_type(
        origin=origin, senders=("sender-433",), subtype=subtype, ref=f"ref:{seam}"
    )


def _session(monkeypatch):
    monkeypatch.setattr("app.session.save_session", lambda *_a, **_k: None)
    monkeypatch.setattr("app.session.add_log", lambda *_a, **_k: 1)
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    from app.session import AgentSession
    return AgentSession(
        id="session-433", name="session-433", scope="/scope-433", cwd="/tmp",
        model="claude-sonnet-5[1m]", role="orchestrator", system_prompt="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seam", "state"),
    (
        ("session.send.compacting", "compacting"),
        ("session.send.running", "running"),
        ("session.send.new_turn", "new_turn"),
    ),
)
async def test_t2_session_send_branch_forwards_provenance(seam, state, monkeypatch):
    from app.session_state import AgentStatus
    provenance = _provenance(seam)
    session = _session(monkeypatch)
    captured = []
    missing = object()

    def record_add_log(*args, **kwargs):
        captured.append((args[2], args[3], kwargs.get("provenance", missing)))
        return 1
    monkeypatch.setattr("app.session.add_log", record_add_log)
    monkeypatch.setattr(
        "app.session.get_runtime",
        lambda _backend: SimpleNamespace(capabilities=SimpleNamespace(mid_turn_inject=False)),
    )

    class AfterNewTurnLog(RuntimeError):
        pass

    if state == "compacting":
        session._compacting = True
    elif state == "running":
        session.status = AgentStatus.RUNNING
    else:
        session.status = AgentStatus.IDLE
        async def stop_after_log(*_args, **_kwargs):
            raise AfterNewTurnLog
        session._ensure_backend = stop_after_log

    try:
        await session.send("writer-body", provenance=provenance)
    except AfterNewTurnLog:
        pass
    except TypeError as error:
        pytest.fail(f"#433 T2 missing writer behavior at distinct seam: {seam}: {error}")
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=False)

    rows = [item for item in captured if item[0] == "user_message"]
    assert len(rows) == 1, (
        f"#433 T2 missing writer behavior at distinct seam: {seam} logged {len(rows)} rows"
    )
    assert rows[0][2] is provenance, (
        f"#433 T2 missing writer behavior at distinct seam: {seam} dropped provenance"
    )


@pytest.mark.asyncio
async def test_t2_compact_direct_log_is_platform_provenance(monkeypatch):
    seam = "session.compact.direct_log"
    _provenance(seam, origin="platform", subtype="compact")
    from app.events import AgentEvent
    session = _session(monkeypatch)
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
    logged = []
    missing = object()
    def record_add_log(*args, **kwargs):
        logged.append((args[2], args[3], kwargs.get("provenance", missing)))
        return 1
    monkeypatch.setattr("app.session.add_log", record_add_log)
    summary = "summary-433 " + "x" * 220

    class CompactBackend:
        session_id = None
        async def connect(self): return None
        async def send(self, _message): return None
        async def events(self):
            yield AgentEvent(type="text", content=summary)
            yield AgentEvent(
                type="turn_end",
                metadata={"ok": True, "stop_reason": "end_turn", "session_id": "compact-433"},
            )
        async def disconnect(self): return None

    backend = CompactBackend()
    ack_scheduled = False
    async def ensure_backend(force_fresh=False):
        nonlocal ack_scheduled
        session._backend = backend
        if not ack_scheduled and session._compact_ack_event is not None:
            async def set_ack():
                await asyncio.sleep(0)
                session._compact_ack_event.set()
            asyncio.create_task(set_ack())
            ack_scheduled = True
        return backend
    session._make_backend = lambda: backend
    session._ensure_backend = ensure_backend

    result = await session.compact()
    if session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=False)
    assert result["ok"] is True
    rows = [item for item in logged if item[0] == "user_message"]
    assert len(rows) == 1, (
        f"#433 T2 missing writer behavior at distinct seam: {seam} did not log once"
    )
    provenance = rows[0][2]
    assert provenance is not missing, (
        f"#433 T2 missing writer behavior at distinct seam: {seam} dropped provenance"
    )
    assert provenance.origin == "platform" and provenance.subtype == "compact"


@pytest.fixture
def writer_db(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "writer-433.db")
    db.init_db()
    base = {
        "scope": "/scope-433", "cwd": "/tmp", "model": "gpt-5.6-sol",
        "system_prompt": "", "status": "idle", "session_id": None,
        "cost_usd": 0.0, "worktree_path": "/tmp", "branch": "task-433/test",
        "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "parent_name": "sender-433",
    }
    db.save_session({**base, "id": "sender-id-433", "name": "sender-433"})
    db.save_session({**base, "id": "target-id-433", "name": "target-433"})
    return db


def test_t2_db_add_log_round_trips_canonical_provenance(writer_db):
    seam = "db.add_log"
    provenance = _provenance(seam)
    try:
        log_id = writer_db.add_log(
            "target-id-433", datetime.now(timezone.utc), "user_message", "roundtrip",
            provenance=provenance,
        )
    except TypeError as error:
        pytest.fail(f"#433 T2 persistence contract missing at {seam}: {error}")
    with writer_db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone())
    assert row["origin"] == "agent"
    assert json.loads(row["origin_detail"])["senders"] == ["sender-433"]
    from app.events import MessageProvenance
    assert MessageProvenance.from_storage(row["origin"], row["origin_detail"]) == provenance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seam",
    ("initial_deliveries.transactional_insert", "message_deliveries.transactional_insert"),
)
async def test_t2_durable_writer_is_atomic_and_persists_receipt_provenance(
    seam, writer_db, monkeypatch,
):
    from app import initial_deliveries, message_deliveries
    provenance = _provenance(seam)
    delivery_id = (
        "00000000-0000-4000-8000-000000004335"
        if seam.startswith("initial")
        else "00000000-0000-4000-8000-000000004336"
    )
    if seam.startswith("initial"):
        monkeypatch.setattr(initial_deliveries, "ensure_delivery_runner", lambda _id: None)
        async def accept_with(value):
            return await initial_deliveries.accept_initial_delivery(
                delivery_id=delivery_id, session_id="target-id-433", worker_name="target-433",
                scope="/scope-433", sender="sender-433", message="durable-initial",
                provenance=value,
            )
        try:
            await accept_with(provenance)
        except TypeError as error:
            pytest.fail(f"#433 T2 missing writer behavior at distinct seam: {seam}: {error}")
        table, prepare = "initial_deliveries", initial_deliveries.prepare_initial_delivery
    else:
        monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _id: None)
        async def accept_with(value):
            return await message_deliveries.accept_message_delivery(
                delivery_id=delivery_id, source_session_id="sender-id-433",
                source_principal="mcp:sender-id-433", source_name="sender-433",
                source_scope="/scope-433", target_session_id="target-id-433",
                target_name="target-433", target_scope="/scope-433",
                target_generation="session=target-id-433|task=|branch=task-433/test|needs_switch=0",
                message="durable-direct", rendered_message="[from:sender-433] durable-direct",
                provenance=value,
            )
        try:
            await accept_with(provenance)
        except TypeError as error:
            pytest.fail(f"#433 T2 missing writer behavior at distinct seam: {seam}: {error}")
        table, prepare = "message_deliveries", message_deliveries.prepare_message_delivery

    with writer_db._conn() as connection:
        receipt = dict(connection.execute(
            f"SELECT * FROM {table} WHERE delivery_id=?", (delivery_id,)
        ).fetchone())
    assert receipt["origin"] == "agent"
    assert json.loads(receipt["origin_detail"])["senders"] == ["sender-433"]
    changed = _provenance(seam, origin="agent", subtype="changed")
    conflict, status = await accept_with(changed)
    assert status == 409 and conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT", (
        f"#433 T2 receipt hash omitted provenance at {seam}"
    )

    trigger = f"fail_{table}_433"
    with writer_db._conn() as connection:
        connection.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} "
            "WHEN NEW.state='PREPARING' BEGIN SELECT RAISE(ABORT, 'forced-433'); END"
        )
    with pytest.raises(Exception, match="forced-433"):
        prepare(delivery_id)
    with writer_db._conn() as connection:
        state = connection.execute(
            f"SELECT state FROM {table} WHERE delivery_id=?", (delivery_id,)
        ).fetchone()[0]
        count = connection.execute(
            "SELECT COUNT(*) FROM logs WHERE session_id=? AND type='user_message'",
            ("target-id-433",),
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER {trigger}")
    assert state == "QUEUED" and count == 0, (
        f"#433 T2 atomicity broken at {seam}: state={state}, user_logs={count}"
    )

    prepared = prepare(delivery_id)
    with writer_db._conn() as connection:
        row = dict(connection.execute(
            "SELECT * FROM logs WHERE id=?", (prepared["user_log_id"],)
        ).fetchone())
        state = connection.execute(
            f"SELECT state FROM {table} WHERE delivery_id=?", (delivery_id,)
        ).fetchone()[0]
    assert state == "PREPARING"
    assert row["origin"] == "agent"
    assert json.loads(row["origin_detail"])["senders"] == ["sender-433"]
