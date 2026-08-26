from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.test_tg_file_deliveries import (
    PRIMARY_CHAT,
    ROOT_EVENT,
    _accept,
    _files,
    batch_world,
)


def test_init_db_migrates_existing_file_outbox_batch_metadata(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "migration-402.db")
    db.init_db()
    with db._conn() as connection:
        connection.execute("DROP INDEX idx_tg_file_deliveries_batch")
        for column in ("batch_id", "batch_index", "batch_group", "batch_kind"):
            connection.execute(f"ALTER TABLE tg_file_deliveries DROP COLUMN {column}")

    db.init_db()
    with db._conn() as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(tg_file_deliveries)",
            ).fetchall()
        }
        indexes = {
            row[1] for row in connection.execute(
                "PRAGMA index_list(tg_file_deliveries)",
            ).fetchall()
        }

    assert {"batch_id", "batch_index", "batch_group", "batch_kind"} <= columns
    assert "idx_tg_file_deliveries_batch" in indexes


@pytest.mark.asyncio
async def test_tg_send_file_route_dispatches_paths_to_batch_with_mirror(monkeypatch):
    from app import auth
    from app import tg_bridge
    from app import tg_file_deliveries
    from app.routes import system
    from app.routes import tg

    monkeypatch.setattr(auth, "validate_session", lambda _cookie: True)
    monkeypatch.setattr(system, "_is_safe_path", lambda _path: True)
    monkeypatch.setattr(
        tg_bridge,
        "config",
        {
            "group_id": -100402001,
            "topics": {"orch-402": 4021},
            "mirrors": {
                "orch-402": {"chat_id": -100402002, "topic_id": 4022},
            },
        },
    )
    monkeypatch.setattr(
        tg_bridge, "_resolve_topic", lambda _scope, _sender: ("orch-402", 4021),
    )
    seen = []

    async def accept(**kwargs):
        seen.append(kwargs)
        return ({
            "ok": True,
            "acceptance": "ACCEPTED",
            "event_id": kwargs["event_id"],
            "delivery_state": "QUEUED",
        }, 202, {})

    monkeypatch.setattr(tg_file_deliveries, "accept_file_batch", accept)
    app = FastAPI()
    app.include_router(tg.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tg/send_file", json={
            "paths": ["/scope/a.png", "/scope/b.pdf"],
            "caption": "batch",
            "scope": "/scope",
            "sender": "worker-402",
            "event_id": "00000000-0000-4000-8000-000000000402",
        })

    assert response.status_code == 202
    assert len(seen) == 1
    call = SimpleNamespace(**seen[0])
    assert call.source_paths == ["/scope/a.png", "/scope/b.pdf"]
    assert call.source_scope == "/scope"
    assert call.source_name == "worker-402"
    assert call.caption == "batch"
    assert call.as_document is False
    assert call.targets == [
        {"target_kind": "primary", "chat_id": -100402001, "thread_id": 4021},
        {"target_kind": "mirror", "chat_id": -100402002, "thread_id": 4022},
    ]


@pytest.mark.asyncio
async def test_tg_send_file_route_reports_atomic_batch_validation_failure(monkeypatch):
    from app import auth
    from app import tg_bridge
    from app import tg_file_deliveries
    from app.routes import system
    from app.routes import tg

    monkeypatch.setattr(auth, "validate_session", lambda _cookie: True)
    monkeypatch.setattr(system, "_is_safe_path", lambda _path: True)
    monkeypatch.setattr(
        tg_bridge,
        "config",
        {"group_id": -100402001, "topics": {"orch-402": 4021}, "mirrors": {}},
    )
    monkeypatch.setattr(
        tg_bridge, "_resolve_topic", lambda _scope, _sender: ("orch-402", 4021),
    )

    async def reject(**_kwargs):
        raise tg_file_deliveries.BatchValidationError([{
            "index": 1,
            "path": "/scope/missing.png",
            "error": "FileNotFoundError",
        }])

    monkeypatch.setattr(tg_file_deliveries, "accept_file_batch", reject)
    app = FastAPI()
    app.include_router(tg.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tg/send_file", json={
            "paths": ["/scope/a.png", "/scope/missing.png"],
            "scope": "/scope",
            "sender": "worker-402",
            "event_id": "00000000-0000-4000-8000-000000000402",
        })

    assert response.status_code == 400
    error = response.json()["error"]
    assert error == {
        "code": "BATCH_FILE_INVALID",
        "message": "batch rejected; no files were accepted",
        "retryable": False,
        "outcome_unknown": False,
        "invalid": [{
            "index": 1,
            "path": "/scope/missing.png",
            "error": "FileNotFoundError",
        }],
    }


@pytest.mark.asyncio
async def test_media_group_timeout_marks_every_file_unknown_without_retry(batch_world):
    world = batch_world
    paths = _files(world.root, ["timeout-a.png", "timeout-b.png", "timeout-c.png"])
    calls = []

    async def timeout(chat_id, media, message_thread_id=None):
        calls.append((chat_id, len(media), message_thread_id))
        raise TimeoutError("ambiguous media-group timeout")

    world.bot.send_media_group = timeout
    await _accept(world, paths)
    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)
    receipt = world.deliveries._resource(ROOT_EVENT)

    assert receipt["delivery_state"] == "UNKNOWN"
    assert [item["delivery_state"] for item in receipt["files"]] == [
        "UNKNOWN", "UNKNOWN", "UNKNOWN",
    ]
    assert receipt["next_action"]["tool"] == "file_delivery_status"
    assert calls == [(PRIMARY_CHAT, 3, 4021)]

    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)
    assert calls == [(PRIMARY_CHAT, 3, 4021)]


@pytest.mark.asyncio
async def test_batch_retries_only_pre_submit_failure_with_same_root_event(batch_world):
    world = batch_world
    paths = _files(world.root, ["retry-a.png", "retry-b.png", "retry-c.png"])
    await _accept(world, paths)
    with world.db._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE batch_id=? ORDER BY batch_index",
            (ROOT_EVENT,),
        ).fetchall()
    Path(rows[1]["snapshot_path"]).unlink()

    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)
    failed = world.deliveries._resource(ROOT_EVENT)
    assert [item["delivery_state"] for item in failed["files"]] == [
        "SENT", "FAILED_BEFORE_SUBMIT", "SENT",
    ]
    assert [len(group["names"]) for group in world.bot.groups] == [2]

    retried, status, _headers = await _accept(world, paths)
    assert status == 202
    assert retried["acceptance"] == "ALREADY_ACCEPTED"
    assert [item["delivery_state"] for item in retried["files"]] == [
        "SENT", "QUEUED", "SENT",
    ]
    await world.deliveries.run_chat_deliveries(PRIMARY_CHAT)
    sent = world.deliveries._resource(ROOT_EVENT)

    assert sent["delivery_state"] == "SENT"
    assert [item["delivery_state"] for item in sent["files"]] == [
        "SENT", "SENT", "SENT",
    ]
    assert len(world.bot.groups) == 1
    assert world.bot.singles == [("photo", "retry-b.png", "")]


@pytest.mark.asyncio
async def test_batch_root_collision_with_single_delivery_returns_conflict(batch_world):
    world = batch_world
    single_path = _files(world.root, ["already-single.png"])[0]
    targets = [{
        "target_kind": "primary",
        "chat_id": PRIMARY_CHAT,
        "thread_id": 4021,
    }]
    _single, single_status, _headers = await world.deliveries.accept_file_delivery(
        event_id=ROOT_EVENT,
        source_session_id="source-402",
        source_name="worker-402",
        source_scope="/scope-402",
        source_path=single_path,
        caption="single",
        as_document=False,
        orch_name="orch-402",
        targets=targets,
    )
    assert single_status == 202
    batch_paths = _files(world.root, ["batch-a.png", "batch-b.png"])

    conflict, status, _headers = await _accept(world, batch_paths)

    assert status == 409
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
