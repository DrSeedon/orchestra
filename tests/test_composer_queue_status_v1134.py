"""Synthetic mailbox/API regressions: state, FIFO, cancellation and recovery."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import mailbox
from app.events import MessageProvenance
from app.routes import sessions
from tests.test_mailbox import db, spy  # isolated DB and manager, no provider calls


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(sessions.router)
    with TestClient(app) as client:
        yield client


def enqueue(body, *, scope="/repo", recipient="recipient", subtype="", origin="user"):
    return mailbox.enqueue(recipient, scope, "synthetic", body, provenance=MessageProvenance(
        origin=origin, senders=("synthetic",), subtype=subtype, ref="synthetic-turn",
    ))


def queue(client, *, scope="/repo", recipient="recipient"):
    response = client.get(f"/api/sessions/{recipient}/queued-messages", params={"scope": scope})
    assert response.status_code == 200
    return response.json()["messages"]


def cancel(client, message_id, *, scope="/repo", recipient="recipient"):
    return client.delete(f"/api/sessions/{recipient}/queued-messages/{message_id}",
                         params={"scope": scope}).json()["cancelled"]


def test_projection_preserves_order_and_old_provenance_without_mutation(client, db):
    first = enqueue("synthetic first")  # old data has no subtype
    second = enqueue("synthetic second", subtype="dashboard", origin="unknown")
    enqueue("synthetic peer only", origin="agent")
    enqueue("synthetic other scope", scope="/other")
    enqueue("synthetic other recipient", recipient="other")
    with db._conn() as connection:
        connection.execute("UPDATE mailbox SET created_at=0 WHERE id=?", (second,))
    for _ in range(2):
        rows = queue(client)
        assert [row["id"] for row in rows] == [first, second]
        assert [row["body"] for row in rows] == ["synthetic first", "synthetic second"]
        assert all(row["state"] == "after_turn" and row["cancellable"] for row in rows)
        assert all(not row["claimed"] for row in rows)
    assert [row["id"] for row in mailbox.claim("recipient", "/repo")][:2] == [first, second]


def test_claim_cancel_race_and_failed_handoff_keep_pending_until_delivery(client):
    first = enqueue("synthetic one")
    second = enqueue("synthetic two")
    mailbox.claim("recipient", "/repo")
    assert cancel(client, first) is False
    assert [(r["state"], r["cancellable"]) for r in queue(client)] == [
        ("handing_off", False), ("handing_off", False),
    ]
    mailbox.release_claim([first, second])
    assert [r["id"] for r in queue(client)] == [first, second]
    assert all(r["cancellable"] for r in queue(client))
    mailbox.claim("recipient", "/repo")
    mailbox.mark_delivered([first])
    assert [r["id"] for r in queue(client)] == [second]
    mailbox.mark_delivered([second])
    assert queue(client) == []


def test_cancellation_is_scoped_and_terminal_rows_disappear(client):
    first = enqueue("synthetic first")
    second = enqueue("synthetic second")
    assert cancel(client, first, scope="/other") is False
    assert cancel(client, first, recipient="other") is False
    assert [r["id"] for r in queue(client)] == [first, second]
    assert cancel(client, first) is True
    assert cancel(client, first) is False
    assert [r["id"] for r in queue(client)] == [second]
    assert cancel(client, second) is True
    assert queue(client) == []


def test_current_turn_backups_are_visible_but_cannot_be_retracted(client):
    pending = enqueue("synthetic submitting", subtype="codex_steer_backup_pending")
    submitted = enqueue("synthetic submitted", subtype="codex_steer_backup")
    after_turn = enqueue("synthetic later", subtype="dashboard")
    rows = queue(client)
    assert [r["state"] for r in rows] == ["current_turn_unconfirmed", "current_turn", "after_turn"]
    assert [r["cancellable"] for r in rows] == [False, False, True]
    assert cancel(client, pending) is False
    assert cancel(client, submitted) is False
    assert cancel(client, after_turn) is True
    mailbox.mark_codex_steer_submitted(pending)
    assert [r["state"] for r in queue(client)] == ["current_turn", "current_turn"]
    mailbox.complete_codex_steers("recipient", "/repo", "synthetic-turn")
    assert queue(client) == []


@pytest.mark.parametrize("method,path", [
    ("get", "/api/sessions/recipient/queued-messages"),
    ("delete", "/api/sessions/recipient/queued-messages/1"),
])
def test_missing_scope_cannot_read_or_cancel(client, method, path):
    message_id = enqueue("synthetic retained")
    assert getattr(client, method)(path).status_code == 400
    assert [r["id"] for r in queue(client)] == [message_id]


@pytest.mark.parametrize("status,queued", [("running", True), ("waiting", True), ("idle", False)])
def test_after_turn_acceptance_does_not_send_active_turn_early(client, spy, status, queued):
    spy.sessions = {"recipient": SimpleNamespace(name="recipient", scope="/repo", status=status)}
    for body in ("synthetic first", "synthetic second"):
        result = asyncio.run(sessions.send_message("recipient", sessions.SendRequest(
            message=body, scope="/repo", channel="dashboard", after_turn=True,
        )))
        assert result.get("queued", False) is queued
    if queued:
        assert spy.sent == []
        assert [r["body"] for r in queue(client)] == ["synthetic first", "synthetic second"]
    else:
        assert len(spy.sent) == 2
        assert queue(client) == []
