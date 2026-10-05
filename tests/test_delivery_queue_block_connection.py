from types import SimpleNamespace


def test_queue_block_reuses_the_open_transaction_connection(monkeypatch):
    from app import message_deliveries

    head = {
        "state": "DELIVERY_UNKNOWN",
        "delivery_id": "head-delivery",
        "updated_at": "2026-10-05T12:00:00+00:00",
    }
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: head)

    monkeypatch.setattr(
        message_deliveries.db,
        "_conn",
        lambda: (_ for _ in ()).throw(AssertionError("opened nested connection")),
    )
    row = {
        "delivery_id": "queued-delivery",
        "payload_hash": "hash",
        "accept_seq": 2,
        "target_session_id": "target-session",
        "state": "QUEUED",
        "error_json": None,
        "provider_ref": None,
    }

    resource = message_deliveries._resource(row, connection=Connection())

    assert resource["next_action"]["code"] == "TARGET_QUEUE_BLOCKED"
    assert len(calls) == 1
    assert "SELECT * FROM message_deliveries" in calls[0][0]
    assert calls[0][1][0] == "target-session"
