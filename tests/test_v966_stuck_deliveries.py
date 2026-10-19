"""V-966: accepted direct messages must not hang forever in a non-terminal state."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import db, mailbox, message_deliveries
from app.events import MessageProvenance
from app.session_state import AgentStatus

SCOPE = "/scope-966"
TARGET = "target-966"
SOURCE = "source-966"
TURN = "codex-turn-966"
PROVENANCE = MessageProvenance(origin="agent", senders=("sender-966",), subtype="direct_message", ref="")


@pytest.fixture
def stuck_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "stuck-966.db")
    db.init_db()
    for sid, status in ((TARGET, "idle"), (SOURCE, "idle")):
        db.save_session({
            "id": sid, "name": sid, "scope": SCOPE, "cwd": "/tmp", "model": "gpt-6-luna",
            "system_prompt": "", "status": status, "session_id": None, "cost_usd": 0.0,
            "worktree_path": "/tmp", "branch": "main", "base_branch": "main",
            "needs_switch": 0, "task_id": "", "role": "worker", "is_orchestrator": False,
            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "parent_name": "",
        })
    message_deliveries._warned_stuck.clear()
    return db


def _insert(delivery_id, seq, state, *, age_s=600, provider_ref=None):
    origin, detail = PROVENANCE.to_storage()
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    with db._conn() as c:
        c.execute(
            """INSERT INTO message_deliveries (
                   accept_seq, delivery_id, schema_version, source_session_id, source_principal,
                   source_name, source_scope, source_task_id, target_session_id, target_name,
                   target_scope, target_task_id, target_generation, message, rendered_message,
                   message_kind, wake, origin, origin_detail, payload_hash, state, created_at,
                   updated_at, provider_ref)
               VALUES (?, ?, 2, ?, 'mcp:s', 'sender-966', ?, '', ?, ?, ?, '', '', ?, ?, 'direct_message',
                   1, ?, ?, ?, ?, ?, ?, ?)""",
            (seq, delivery_id, SOURCE, SCOPE, TARGET, TARGET, SCOPE, f"body-{delivery_id}",
             f"body-{delivery_id}", origin, detail, f"h-{seq}", state, stamp, stamp, provider_ref),
        )


def _state(delivery_id):
    return message_deliveries._row(delivery_id)["state"]


def test_archiving_target_fails_pending_deliveries_visibly(stuck_db):
    _insert("d-wait", 1, "WAITING_NEXT_TURN", provider_ref=f"steered:{TURN}")
    _insert("d-queued", 2, "QUEUED")
    _insert("d-done", 3, "SUBMITTED")
    _insert("d-unknown", 4, "DELIVERY_UNKNOWN")
    origin, detail = PROVENANCE.to_storage()
    mailbox.enqueue(TARGET, SCOPE, "sender-966", "body-d-wait", provenance=MessageProvenance(
        origin="agent", senders=("sender-966",), subtype="direct_message_recovery", ref="d-wait"))

    db.archive_session(TARGET)

    assert _state("d-wait") == "FAILED_BEFORE_SUBMIT"
    assert _state("d-queued") == "FAILED_BEFORE_SUBMIT"
    assert _state("d-done") == "SUBMITTED"
    assert _state("d-unknown") == "DELIVERY_UNKNOWN"  # at-most-once: ambiguous ones stay untouched
    error = json.loads(message_deliveries._row("d-queued")["error_json"])
    assert error["code"] == "TARGET_ARCHIVED" and error["outcome_unknown"] is False
    with db._conn() as c:
        notices = {r[0] for r in c.execute("SELECT delivery_id FROM message_delivery_failure_notices")}
    assert notices == {"d-wait", "d-queued"}
    assert mailbox.pending(TARGET, SCOPE) == []


@pytest.mark.asyncio
async def test_sweep_wakes_idle_target_blocked_by_waiting_next_turn(stuck_db):
    _insert("d-head", 1, "WAITING_NEXT_TURN", provider_ref=f"steered:{TURN}")
    _insert("d-behind", 2, "QUEUED")
    with db._conn() as c:
        c.execute(
            "UPDATE message_deliveries SET provider_ref=? WHERE delivery_id='d-head'",
            (f"steered:{TURN}",),
        )
    mailbox.enqueue(TARGET, SCOPE, "sender-966", "body-d-head", provenance=MessageProvenance(
        origin="agent", senders=("sender-966",), subtype="direct_message_recovery", ref="d-head"))

    sent = []

    class Session:
        id = TARGET
        name = TARGET
        scope = SCOPE
        status = AgentStatus.IDLE
        _compacting = False

        def __init__(self):
            from app.session_turns import TurnManager
            self._turns = TurnManager(self)

        def _log(self, *a, **k):
            pass

        def _spawn_bg(self, coro):
            return asyncio.ensure_future(coro)

        async def send(self, text, *, provenance):
            sent.append(text)

    session = Session()

    class Manager:
        sessions = {TARGET: session}

    result = await message_deliveries.sweep_stuck_deliveries(Manager())
    await asyncio.sleep(0.05)

    assert result["woken"] == 1
    assert sent and "body-d-head" in sent[0]
    assert _state("d-head") == "SUBMITTED"


@pytest.mark.asyncio
async def test_sweep_leaves_recent_waiting_turn_alone(stuck_db):
    _insert("d-fresh", 1, "WAITING_NEXT_TURN", age_s=5)

    class Manager:
        sessions = {}

    result = await message_deliveries.sweep_stuck_deliveries(Manager())
    assert result["woken"] == 0 and _state("d-fresh") == "WAITING_NEXT_TURN"


@pytest.mark.asyncio
async def test_long_stuck_delivery_is_named_once_in_target_log(stuck_db):
    _insert("d-old", 1, "QUEUED", age_s=7200)

    class Manager:
        sessions = {}

    await message_deliveries.sweep_stuck_deliveries(Manager())
    await message_deliveries.sweep_stuck_deliveries(Manager())
    with db._conn() as c:
        warnings = c.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='warning'", (TARGET,)
        ).fetchall()
    assert len(warnings) == 1 and "d-old" in warnings[0][0]


@pytest.mark.asyncio
async def test_sweep_fails_rows_left_behind_by_an_earlier_archive(stuck_db):
    # Records written before the archive hook existed: the session is already archived.
    _insert("d-legacy-wait", 1, "WAITING_NEXT_TURN")
    _insert("d-legacy-queued", 2, "QUEUED")
    with db._conn() as c:
        c.execute("UPDATE sessions SET status='archived' WHERE id=?", (TARGET,))

    class Manager:
        sessions = {}

    result = await message_deliveries.sweep_stuck_deliveries(Manager())

    assert result["archived"] == 2
    assert _state("d-legacy-wait") == _state("d-legacy-queued") == "FAILED_BEFORE_SUBMIT"
