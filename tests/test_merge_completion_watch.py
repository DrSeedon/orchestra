import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def watch_db(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "watch.db")
    db.init_db()


@pytest.mark.asyncio
async def test_merge_mcp_returns_immediately_only_with_durable_completion(monkeypatch):
    from app import mcp_stdio as m
    from app.routes import merge_operations as route
    from app.bg_jobs import bg_manager
    from app import db

    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "caller")
    monkeypatch.setattr(m, "SESSION_ID", "caller-id")
    monkeypatch.setattr(db, "get_session", lambda sid: {"id": sid, "scope": "/s", "name": "renamed-caller"})
    create = AsyncMock(return_value={"id": "bg-test", "type": "merge", "status": "active"})
    monkeypatch.setattr(bg_manager, "create", create)
    async def accept(**kwargs):
        return {"operation_id": kwargs["operation_id"], "operation_state": "RUNNING"}, 202
    monkeypatch.setattr(route, "accept_merge_operation", accept)
    async def api(method, path, **kwargs):
        assert method == "POST" and path == "/api/merge-operations"
        response = await route.create_merge_operation(kwargs["json"])
        return json.loads(response.body)
    monkeypatch.setattr(m, "_api", api)
    wait = AsyncMock(side_effect=AssertionError("durable completion must not poll"))
    monkeypatch.setattr(m, "_await_merge_terminal", wait)
    result = await m.merge_worker("worker")
    assert result.isError is False
    assert result.structuredContent["result"]["completion"]["job_id"] == "bg-test"
    assert "Do not poll" in result.content[0].text
    assert create.call_args.kwargs["target_session_id"] == "caller-id"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "PARTIAL", "UNKNOWN", "RUNNING"])
async def test_watch_delivers_terminal_state_to_pinned_session(watch_db, monkeypatch, state):
    from app.bg_jobs import BgJobManager
    from app import merge_operations, db
    record = {"scope": "/s", "result": {"operation_id": "op1", "operation_state": "RUNNING"}}
    monkeypatch.setattr(merge_operations, "get_operation_record", lambda _: record)
    manager = MagicMock()
    manager.ensure_loaded_by_id = AsyncMock(return_value=MagicMock(id="pinned-id"))
    manager.send = AsyncMock()
    bg = BgJobManager()
    bg.set_session_manager(manager)
    try:
        job, duplicate = await asyncio.gather(*[
            bg.create("merge", {"operation_id": "op1"}, "Merge completion",
                      "pinned-id", "old-name", "/s", "caller")
            for _ in range(2)
        ])
        assert "error" not in job
        assert duplicate["id"] == job["id"]
        record["result"]["operation_state"] = state
        if state == "RUNNING":
            record["result"]["error"] = {"code": "TARGET_DIRTY", "message": "caller action needed"}
            record["result"]["next_action"] = {"message": "Inspect the target workspace"}
        async with asyncio.timeout(5):
            while not manager.send.called:
                await asyncio.sleep(.01)
        assert manager.send.call_args.args[0] == "pinned-id"
        assert state in str(manager.send.call_args.args[1])
        assert db.bg_get_job(job["id"])["status"] == "triggered"
    finally:
        await bg.shutdown()


@pytest.mark.asyncio
async def test_watch_rejects_other_scope(watch_db, monkeypatch):
    from app.bg_jobs import BgJobManager
    from app import merge_operations
    monkeypatch.setattr(merge_operations, "get_operation_record", lambda _: {"scope": "/other"})
    bg = BgJobManager()
    result = await bg.create("merge", {"operation_id": "op1"}, "completion", "s1", "w", "/s", "w")
    assert "scope" in result["error"]
    assert not bg._tasks


@pytest.mark.asyncio
async def test_watch_restores_after_restart(watch_db, monkeypatch):
    from app.bg_jobs import BgJobManager
    from app import merge_operations
    record = {"scope": "/s", "result": {"operation_id": "op1", "operation_state": "RUNNING"}}
    monkeypatch.setattr(merge_operations, "get_operation_record", lambda _: record)
    bg = BgJobManager()
    job = await bg.create("merge", {"operation_id": "op1"}, "completion", "s1", "w", "/s", "w")
    await bg.shutdown()
    restored = BgJobManager()
    manager = MagicMock()
    manager.ensure_loaded_by_id = AsyncMock(return_value=MagicMock())
    manager.send = AsyncMock()
    restored.set_session_manager(manager)
    record["result"]["operation_state"] = "SUCCEEDED"
    try:
        await restored.restore_from_db()
        async with asyncio.timeout(5):
            while not manager.send.called:
                await asyncio.sleep(.01)
        assert job["id"] in manager.send.call_args.kwargs["provenance"].ref
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_slow_status_request_cannot_exceed_merge_wait_budget(monkeypatch):
    from app import mcp_stdio as m
    async def stuck(_):
        await asyncio.Event().wait()
    monkeypatch.setattr(m, "_MERGE_WAIT_SECONDS", .01)
    monkeypatch.setattr(m, "_recover_merge_status", stuck)
    running = {"operation_id": "op1", "operation_state": "RUNNING"}
    async with asyncio.timeout(1):
        assert await m._await_merge_terminal("op1", running) == running


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_scope,registration_error", [("/other", False), ("/s", True)])
async def test_watch_not_confirmed_keeps_synchronous_recovery(monkeypatch, caller_scope, registration_error):
    from app import mcp_stdio as m, db
    from app.routes import merge_operations as route
    from app.bg_jobs import bg_manager

    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "SESSION_ID", "caller-id")
    monkeypatch.setattr(db, "get_session", lambda _: {"scope": caller_scope, "name": "caller"})
    create = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    monkeypatch.setattr(bg_manager, "create", create)
    async def accept(**kwargs):
        return {"operation_id": kwargs["operation_id"], "operation_state": "RUNNING"}, 202
    monkeypatch.setattr(route, "accept_merge_operation", accept)
    async def api(method, path, **kwargs):
        response = await route.create_merge_operation(kwargs["json"])
        return json.loads(response.body)
    monkeypatch.setattr(m, "_api", api)
    wait = AsyncMock(return_value={"operation_id": "op1", "operation_state": "SUCCEEDED"})
    monkeypatch.setattr(m, "_await_merge_terminal", wait)
    result = await m.merge_worker("worker")
    wait.assert_awaited_once()
    assert create.called is registration_error
    assert result.structuredContent["result"]["operation_state"] == "SUCCEEDED"
