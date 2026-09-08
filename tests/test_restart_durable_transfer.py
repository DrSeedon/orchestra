from unittest.mock import MagicMock

import pytest

@pytest.fixture
def inbox(tmp_path, monkeypatch):
    from app import db, restart_inbox
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'db.sqlite')
    db.init_db()
    with db._conn() as c:
        c.execute("INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES ('s','worker','/repo','/repo','gpt-5.6-sol','2026-09-08')")
    monkeypatch.setattr('app.message_deliveries.ensure_target_runner', MagicMock())
    return db, restart_inbox


@pytest.mark.asyncio
async def test_failed_inbox_ack_reuses_same_durable_delivery(inbox, monkeypatch):
    db, module = inbox
    module.enqueue('s', 'Do this once')
    original = module.mark_delivered
    monkeypatch.setattr(module, 'mark_delivered', MagicMock(side_effect=OSError('ack failed')))
    assert await module.deliver_pending(None) == 1
    with db._conn() as c:
        first = dict(c.execute('SELECT * FROM message_deliveries').fetchone())
        # An ambiguous provider outcome is not made QUEUED again by another inbox drain.
        c.execute("UPDATE message_deliveries SET state='DELIVERY_UNKNOWN'")
    monkeypatch.setattr(module, 'mark_delivered', original)
    assert await module.deliver_pending(None) == 1
    assert module.pending() == []
    with db._conn() as c:
        rows = c.execute('SELECT delivery_id,state FROM message_deliveries').fetchall()
    assert [tuple(row) for row in rows] == [(first['delivery_id'], 'DELIVERY_UNKNOWN')]


@pytest.mark.asyncio
async def test_inbox_does_not_drop_missing_target(inbox, monkeypatch):
    db, module = inbox
    module.enqueue('missing', 'retained')
    assert await module.deliver_pending(None) == 0
    assert module.pending()[0]['attempts'] == 1
    with db._conn() as c:
        assert c.execute('SELECT count(*) FROM message_deliveries').fetchone()[0] == 0
