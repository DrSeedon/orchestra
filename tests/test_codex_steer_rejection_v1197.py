"""Offline RPC -> session -> durable FIFO regression for V-1197."""

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app import db, message_deliveries as deliveries
from app.backend_codex import (
    CodexBackend, CodexProtocolError, CodexSubmissionRejectedError,
)
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus


FIRST = "00000000-0000-4000-8000-000000001197"
SECOND = "00000000-0000-4000-8000-000000001198"


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fifo.db")
    db.init_db()
    monkeypatch.setattr(deliveries, "ensure_target_runner", lambda _target: None)
    monkeypatch.setattr(deliveries, "notify_message_delivery_failure", AsyncMock())
    session = AgentSession(
        id="target-1197", name="target-1197", scope="/synthetic-1197",
        cwd=str(tmp_path), model="gpt-6.1-sol", backend_type="codex",
        created_at=datetime.now(timezone.utc),
    )
    record = {
        "id": session.id, "name": session.name, "scope": session.scope,
        "cwd": session.cwd, "model": session.model, "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "is_orchestrator": False,
        "color": "", "created_at": session.created_at.isoformat(), "finished_at": None,
    }
    db.save_session(record)
    source = dict(record, id="source-1197", name="source-1197")
    db.save_session(source)
    backend = CodexBackend(model=session.model, cwd=str(tmp_path))
    stream = asyncio.StreamReader()
    backend._proc = SimpleNamespace(
        returncode=None, stdout=stream, stdin=object(), wait=AsyncMock(return_value=0),
    )
    backend._thread_id = "thread-1197"
    backend._active_turn_id = "turn-1197"
    session.status = AgentStatus.RUNNING
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._note_next_precompact_activity = MagicMock()
    session._attach_pending_facts = lambda message: (message, [])
    session._ack_pending_facts = MagicMock()
    session._log = MagicMock()
    session._persist = MagicMock()
    calls = []

    async def write(payload):
        calls.append(payload)
        response = {"id": payload["id"]}
        if len(calls) == 1:
            response["error"] = {"code": -32600, "message": "no active turn to steer"}
        else:
            response["result"] = {"turnId": "turn-1197"}
        stream.feed_data((json.dumps(response) + "\n").encode())

    backend._write = write

    class Manager:
        async def send_message_delivery(self, session_id, message, *, delivery,
                                        target_generation, provenance):
            assert session_id == session.id
            await session.send(message, delivery=delivery, provenance=provenance)

    async def accept(delivery_id):
        return await deliveries.accept_message_delivery(
            delivery_id=delivery_id, source_session_id=source["id"],
            source_name=source["name"], source_scope=session.scope,
            target_session_id=session.id, target_name=session.name,
            target_scope=session.scope, target_generation="synthetic-generation",
            message=delivery_id, rendered_message=delivery_id,
            provenance=MessageProvenance(
                origin="agent", senders=(source["name"],),
                subtype="direct_message", ref=delivery_id,
            ),
        )

    return SimpleNamespace(
        session=session, backend=backend, stream=stream, calls=calls,
        manager=Manager(), accept=accept,
    )


@pytest.mark.asyncio
async def test_correlated_rejection_releases_fifo_through_real_session(harness):
    h = harness
    await h.accept(FIRST)
    await h.accept(SECOND)
    reader = asyncio.create_task(h.backend._read_stdout())
    try:
        assert await deliveries.run_target_message_deliveries(
            h.session.id, manager=h.manager,
        ) is True
        first = deliveries.get_message_delivery(FIRST, "source-1197")
        assert first["delivery_state"] == "FAILED_BEFORE_SUBMIT"
        assert first["error"]["code"] == "PROVIDER_REJECTED"
        assert first["error"]["outcome_unknown"] is False
        assert deliveries._row(SECOND)["state"] == "SUBMITTED"
        assert [p["params"]["input"][0]["text"] for p in h.calls] == [FIRST, SECOND]
        assert h.backend._pending_requests == {}
        assert h.session._pending_messages == []
        with db._conn() as connection:
            logs = connection.execute("SELECT content FROM logs WHERE type='user_message'").fetchall()
            notices = connection.execute("SELECT * FROM message_delivery_failure_notices").fetchall()
        # Refused input cannot leak into a later turn through restored history.
        assert [row["content"] for row in logs] == [SECOND]
        assert len(notices) == 1
        deliveries.notify_message_delivery_failure.assert_awaited_once()
    finally:
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    "timeout", "disconnect", "cancel", "lookalike", "internal_error",
    "wrong_code", "different_message", "start_rejection",
])
async def test_ambiguous_failures_keep_fifo_barrier_and_same_id_dedup(harness, failure):
    h = harness
    await h.accept(FIRST)
    await h.accept(SECOND)

    async def fail(payload):
        h.calls.append(payload)
        if failure == "timeout":
            raise TimeoutError("acknowledgement lost")
        if failure == "lookalike":
            raise RuntimeError("request: no active turn to steer")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "disconnect":
            h.stream.feed_eof()
            return
        error = {"code": -32600, "message": "no active turn to steer"}
        if failure == "internal_error":
            error["message"] = "internal error after possible acceptance"
        if failure == "wrong_code":
            error["code"] = -32603
        if failure == "different_message":
            error["message"] += "; completion unknown"
        h.stream.feed_data((json.dumps({"id": payload["id"], "error": error}) + "\n").encode())

    if failure == "start_rejection":
        h.backend._active_turn_id = None
        h.backend._reload_stale_managed_config_before_turn = AsyncMock()
    h.backend._write = fail
    reader = asyncio.create_task(h.backend._read_stdout())
    try:
        with pytest.raises((RuntimeError, TimeoutError, asyncio.CancelledError)):
            await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager)
        first = deliveries.get_message_delivery(FIRST, "source-1197")
        assert first["delivery_state"] == "DELIVERY_UNKNOWN"
        assert first["error"]["outcome_unknown"] is True
        assert first["next_action"]["retryable"] is False
        repeated, status = await h.accept(FIRST)
        assert status == 202
        assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
        assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager) is False
        assert len(h.calls) == 1
        assert deliveries._row(SECOND)["state"] == "QUEUED"
        assert h.backend._pending_requests == {}
    finally:
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


@pytest.mark.asyncio
async def test_unrelated_response_cannot_reject_current_submission(harness):
    h = harness
    await h.accept(FIRST)

    async def unrelated_then_ack(payload):
        h.calls.append(payload)
        for response in (
            {"id": payload["id"] + 1000,
             "error": {"code": -32600, "message": "no active turn to steer"}},
            {"id": payload["id"], "result": {"turnId": "turn-1197"}},
        ):
            h.stream.feed_data((json.dumps(response) + "\n").encode())

    h.backend._write = unrelated_then_ack
    reader = asyncio.create_task(h.backend._read_stdout())
    try:
        assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager)
        assert deliveries._row(FIRST)["state"] == "SUBMITTED"
        assert len(h.calls) == 1
    finally:
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


@pytest.mark.asyncio
async def test_concurrent_runners_recovery_and_explicit_retry_have_no_loss_or_duplicates(harness):
    h = harness
    await h.accept(FIRST)
    entered, release = asyncio.Event(), asyncio.Event()
    original_write = h.backend._write

    async def blocked_write(payload):
        if not h.calls:
            entered.set()
            await release.wait()
        await original_write(payload)

    h.backend._write = blocked_write
    reader = asyncio.create_task(h.backend._read_stdout())
    runner = asyncio.create_task(deliveries.run_target_message_deliveries(h.session.id, manager=h.manager))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        repeated, _ = await h.accept(FIRST)
        assert repeated["delivery_state"] == "DISPATCHING"
        await h.accept(SECOND)
        concurrent = asyncio.create_task(deliveries.run_target_message_deliveries(h.session.id, manager=h.manager))
        release.set()
        assert await asyncio.gather(runner, concurrent) == [True, True]
        assert len(h.calls) == 2
        rejected = dict(deliveries._row(FIRST))
        # A second failure observer must not replace the receipt or duplicate its notice.
        observer = deliveries.MessageDeliveryContext(
            FIRST, history_user_message=FIRST,
            provenance=MessageProvenance(origin="agent", senders=("source-1197",)),
        )
        observer.dispatched = True
        await observer.mark_unknown(RuntimeError("late observer"))
        assert dict(deliveries._row(FIRST)) == rejected
        assert await deliveries.recover_message_deliveries(target_session_id=h.session.id) == 0
        assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager)
        assert len(h.calls) == 2
        assert dict(deliveries._row(FIRST)) == rejected
        with db._conn() as connection:
            assert connection.execute("SELECT count(*) FROM message_delivery_failure_notices").fetchone()[0] == 1

        # Only an explicit same-key retry is allowed to submit the refused input.
        repeated, _ = await h.accept(FIRST)
        assert repeated["delivery_state"] == "PREPARING"
        assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager)
        assert deliveries._row(FIRST)["state"] == "SUBMITTED"
        assert len(h.calls) == 3
        await h.accept(FIRST)
        assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager)
        assert len(h.calls) == 3
        with db._conn() as connection:
            messages = connection.execute("SELECT content FROM logs WHERE type='user_message'").fetchall()
        assert sorted(row["content"] for row in messages) == [FIRST, SECOND]
        # A late rejection cannot demote a successful receipt.
        deliveries.mark_message_delivery_unknown(FIRST, CodexSubmissionRejectedError(
            "turn/steer", {"code": -32600, "message": "no active turn to steer"},
        ))
        assert deliveries._row(FIRST)["state"] == "SUBMITTED"
    finally:
        release.set()
        if not runner.done():
            runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


@pytest.mark.asyncio
async def test_legacy_unknown_is_not_reclassified_and_teardown_never_replays_it(harness):
    h = harness
    await h.accept(FIRST)
    await h.accept(SECOND)
    deliveries.prepare_message_delivery(FIRST)
    deliveries.mark_message_delivery_dispatching(FIRST)
    # Even the old exception with identical text is insufficient evidence.
    deliveries.mark_message_delivery_unknown(FIRST, CodexProtocolError(
        "request", {"code": -32600, "message": "no active turn to steer"},
    ))
    before = dict(deliveries._row(FIRST))
    deliveries.mark_message_delivery_unknown(FIRST, CodexSubmissionRejectedError(
        "turn/steer", {"code": -32600, "message": "no active turn to steer"},
    ))
    assert dict(deliveries._row(FIRST)) == before
    assert await deliveries.run_target_message_deliveries(h.session.id, manager=h.manager) is False
    assert h.calls == []
    # Existing recovery requires prior runtime teardown; it releases the barrier
    # as ORPHANED, preserving the uncertain receipt and never resending its input.
    h.backend._proc = None
    assert await deliveries.recover_message_deliveries(target_session_id=h.session.id) == 1
    assert deliveries._row(FIRST)["state"] == "DELIVERY_UNKNOWN_ORPHANED"
    assert deliveries._row(SECOND)["state"] == "QUEUED"
    repeated, _ = await h.accept(FIRST)
    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN_ORPHANED"
    # Inspect the next eligible payload without starting a new provider runtime.
    assert deliveries._next_target_delivery(h.session.id)["delivery_id"] == SECOND
    assert h.calls == []


@pytest.mark.asyncio
async def test_rejection_and_failure_notice_commit_atomically(harness, monkeypatch):
    h = harness
    await h.accept(FIRST)
    deliveries.prepare_message_delivery(FIRST)
    deliveries.mark_message_delivery_dispatching(FIRST)
    refusal = CodexSubmissionRejectedError(
        "turn/steer", {"code": -32600, "message": "no active turn to steer"},
    )
    before = dict(deliveries._row(FIRST))
    with monkeypatch.context() as patch:
        patch.setattr(deliveries, "record_delivery_failure", MagicMock(
            side_effect=RuntimeError("synthetic notice storage failure"),
        ))
        with pytest.raises(RuntimeError, match="notice storage failure"):
            deliveries.mark_message_delivery_unknown(FIRST, refusal)
    assert dict(deliveries._row(FIRST)) == before
    with db._conn() as connection:
        assert connection.execute("SELECT content FROM logs WHERE id=?", (before["user_log_id"],)).fetchone()[0] == FIRST
    result = deliveries.mark_message_delivery_unknown(FIRST, refusal)
    assert result["delivery_state"] == "FAILED_BEFORE_SUBMIT"
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM message_delivery_failure_notices").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_concurrent_rejection_observers_preserve_one_durable_notice(harness):
    import threading

    h = harness
    await h.accept(FIRST)
    deliveries.prepare_message_delivery(FIRST)
    deliveries.mark_message_delivery_dispatching(FIRST)
    barrier = threading.Barrier(2, timeout=3)

    def observe():
        barrier.wait()
        return deliveries.mark_message_delivery_unknown(FIRST, CodexSubmissionRejectedError(
            "turn/steer", {"code": -32600, "message": "no active turn to steer"},
        ))

    results = await asyncio.gather(asyncio.to_thread(observe), asyncio.to_thread(observe))
    assert [row["delivery_state"] for row in results] == ["FAILED_BEFORE_SUBMIT"] * 2
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM message_delivery_failure_notices").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM logs WHERE type='user_message'").fetchone()[0] == 0
