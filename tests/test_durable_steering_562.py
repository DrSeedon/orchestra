"""#V-562: active-turn steers survive a failed terminal event."""

from datetime import datetime, timezone

import pytest

from app import db, mailbox, message_deliveries
from app.events import MessageProvenance


TARGET = "target-562"
SCOPE = "/scope-562"
TURN = "codex-turn-562"
PROVENANCE = MessageProvenance(
    origin="agent", senders=("sender-562",), subtype="direct_message", ref="",
)


@pytest.fixture
def message_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "steering-562.db")
    db.init_db()
    return db


def _insert_delivery(delivery_id: str, body: str, seq: int) -> None:
    origin, detail = PROVENANCE.to_storage()
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        connection.execute(
            """INSERT INTO message_deliveries (
                   accept_seq, delivery_id, schema_version, source_session_id,
                   source_principal, source_name, source_scope, source_task_id,
                   target_session_id, target_name, target_scope, target_task_id,
                   target_generation, message, rendered_message, message_kind, wake,
                   origin, origin_detail, payload_hash, state, created_at, updated_at,
                   provider_ref
               ) VALUES (?, ?, 2, 'source-562', 'mcp:source-562', 'sender-562',
                   '/source-562', '', ?, ?, ?, '', '', ?, ?, 'direct_message', 1,
                   ?, ?, ?, 'SUBMITTED', ?, ?, ?)""",
            (
                seq, delivery_id, TARGET, TARGET, SCOPE, body, body,
                origin, detail, f"hash-{seq}", now, now, f"steered:{TURN}",
            ),
        )


def test_failed_turn_requeues_all_steers_fifo_and_is_idempotent(message_db):
    _insert_delivery("delivery-562-a", "первое срочное", 1)
    _insert_delivery("delivery-562-b", "второе срочное", 2)

    assert message_deliveries.requeue_failed_turn(TARGET, TURN) == 2
    assert message_deliveries.requeue_failed_turn(TARGET, TURN) == 0

    queued = mailbox.pending(TARGET, SCOPE)
    assert [item["body"] for item in queued] == ["первое срочное", "второе срочное"]
    assert [item["sender"] for item in queued] == ["sender-562", "sender-562"]
    assert all(
        message_deliveries._row(delivery_id)["state"] == "WAITING_NEXT_TURN"
        for delivery_id in ("delivery-562-a", "delivery-562-b")
    )
    receipt = message_deliveries._resource(
        message_deliveries._row("delivery-562-a"),
    )
    assert receipt["next_action"]["code"] == "WAITING_NEXT_TURN"


def test_successful_turn_does_not_requeue_regular_delivery(message_db):
    _insert_delivery("delivery-562-success", "не повторять", 1)
    with db._conn() as connection:
        connection.execute(
            "UPDATE message_deliveries SET provider_ref='ordinary-turn-562' "
            "WHERE delivery_id='delivery-562-success'"
        )

    assert message_deliveries.requeue_failed_turn(TARGET, "ordinary-turn-562") == 0
    assert mailbox.pending(TARGET, SCOPE) == []
    assert message_deliveries._row("delivery-562-success")["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_recovered_mailbox_delivery_completes_receipts_atomically(message_db):
    _insert_delivery("delivery-562", "доставить на следующем ходу", 1)
    assert message_deliveries.requeue_failed_turn(TARGET, TURN) == 1
    queued = mailbox.claim(TARGET, SCOPE)

    class Session:
        def __init__(self):
            self.sent = []

        async def send(self, text, *, provenance):
            self.sent.append((text, provenance))

    session = Session()
    from app.session_turns import TurnManager

    await TurnManager(session)._deliver_mailbox(queued)

    assert mailbox.pending(TARGET, SCOPE) == []
    assert message_deliveries._row("delivery-562")["state"] == "SUBMITTED"
    assert session.sent[0][0] == "[from:sender-562] доставить на следующем ходу"


def test_context_marks_only_running_steer_with_turn_identity(message_db):
    delivery_id = "00000000-0000-4000-8000-000000000562"
    _insert_delivery(delivery_id, "маркер", 1)
    context = message_deliveries.MessageDeliveryContext(
        delivery_id,
        history_user_message="маркер",
        provenance=PROVENANCE,
    )
    context.mark_running_steer()

    import asyncio
    with db._conn() as connection:
        connection.execute(
            "UPDATE message_deliveries SET state='PREPARING' WHERE delivery_id=?",
            (delivery_id,),
        )

    async def submit():
        await context.before_submit()
        await context.mark_submitted(provider_ref=TURN)

    asyncio.run(submit())
    assert message_deliveries._row(delivery_id)["provider_ref"] == f"steered:{TURN}"
    assert message_deliveries._resource(message_deliveries._row(delivery_id))["provider_ref"] == TURN


def test_codex_process_exit_keeps_active_turn_identity_for_recovery():
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
    backend._thread_id = "thread-562"
    backend._active_turn_id = TURN

    event = backend._convert_notification({
        "method": "_process/exited",
        "params": {"returncode": 1, "stderr": "provider stopped"},
    })[0]

    assert event.metadata["event_id"] == TURN
    assert backend.active_turn_id is None
