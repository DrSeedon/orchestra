"""Frozen Phase-2 acceptance oracles for #395 task-create request identity."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import json
import threading

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _seed_project() -> None:
    from app import tm
    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")


def _request(key: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/tm/tasks",
        "headers": [(b"idempotency-key", key.encode("ascii"))],
    })


async def _create(key: str, *, title: str = "idempotent task", project: str = "project"):
    from app.routes.tm import TmTaskCreate, tm_create_task

    return await tm_create_task(
        TmTaskCreate(project=project, title=title),
        _request(key),
    )


def _payload(response):
    if isinstance(response, JSONResponse):
        return json.loads(response.body)
    return response


def _canonical_store(tmp_path):
    from app import tm
    from app.db import init_db
    from app.ia.task_store import TaskStore, build_migration_manifest
    from tests.test_knowledge_runtime_debt_361 import _task_projection_snapshot

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "orchestra", scope="/scope")
        tm.create_task(
            connection,
            "orchestra",
            "projection recovery",
            par_number=405,
        )
        connection.commit()
    store = TaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(_task_projection_snapshot()))
    return store


@pytest.mark.asyncio
async def test_t5_same_key_concurrent_calls_create_one_durable_task():
    from app import tm

    _seed_project()
    first, second = await asyncio.gather(
        _create("request-key-0001"),
        _create("request-key-0001"),
    )
    first_payload = _payload(first)
    second_payload = _payload(second)

    assert not isinstance(first, JSONResponse)
    assert not isinstance(second, JSONResponse)
    assert first_payload["id"] == second_payload["id"]
    assert {first_payload["replayed"], second_payload["replayed"]} == {False, True}
    assert first_payload["request_key"] == second_payload["request_key"] == "request-key-0001"
    with tm._conn() as connection:
        assert connection.execute("SELECT count(*) FROM tm_tasks").fetchone()[0] == 1
        receipt = connection.execute(
            "SELECT fingerprint,state,task_id,par_number,response_json "
            "FROM tm_task_create_requests WHERE project_id=? AND request_key=?",
            ("project", "request-key-0001"),
        ).fetchone()
    assert receipt is not None
    assert receipt["fingerprint"].startswith("sha256:")
    assert receipt["state"] == "MIRRORS_COMMITTED"
    assert str(receipt["task_id"]) == str(first_payload["id"])
    assert str(receipt["par_number"]) == str(first_payload["par"])
    assert json.loads(receipt["response_json"])["id"] == first_payload["id"]


@pytest.mark.asyncio
async def test_t5_same_key_different_body_is_conflict_without_second_task():
    from app import tm

    _seed_project()
    first = await _create("request-key-0002", title="first body")
    conflict = await _create("request-key-0002", title="different body")

    assert not isinstance(first, JSONResponse)
    assert isinstance(conflict, JSONResponse)
    assert conflict.status_code == 409
    payload = _payload(conflict)
    assert payload["reason"] == "IDEMPOTENCY_FINGERPRINT_MISMATCH"
    assert payload["request_key"] == "request-key-0002"
    with tm._conn() as connection:
        assert connection.execute("SELECT count(*) FROM tm_tasks").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_t5_retry_after_active_commit_replays_while_mirror_is_failed():
    from app import tm

    class FailedMirror:
        canonical_head = "canonical-old"
        projection_head = "projection-old"

        def task_create(self, **_kwargs):
            raise RuntimeError("injected mirror failure")

        def record_debt(self, _debt):
            return None

    _seed_project()
    with tm.ia_process_task_store_mode(store=FailedMirror(), mode="shadow"):
        first = _payload(await _create("request-key-0003"))
        replay = _payload(await _create("request-key-0003"))

    assert first["id"] == replay["id"]
    assert replay["replayed"] is True
    assert replay["request_key"] == "request-key-0003"
    with tm._conn() as connection:
        assert connection.execute("SELECT count(*) FROM tm_tasks").fetchone()[0] == 1
        receipt = connection.execute(
            "SELECT state,error_json FROM tm_task_create_requests "
            "WHERE project_id=? AND request_key=?",
            ("project", "request-key-0003"),
        ).fetchone()
    assert receipt["state"] == "ACTIVE_COMMITTED"
    assert "injected mirror failure" in receipt["error_json"]


@pytest.mark.asyncio
async def test_t5_mcp_reuses_request_key_and_exposes_status_lookup(monkeypatch):
    import app.mcp_stdio as mcp
    from app.routes import tm as tm_route

    assert "request_key" in inspect.signature(mcp.task_create).parameters
    assert hasattr(mcp, "task_create_status")
    assert "/api/tm/task-create-requests/{request_key}" in {
        route.path for route in tm_route.router.routes
    }
    seen = {}

    async def fake_api(method, path, **kwargs):
        seen.update(method=method, path=path, kwargs=kwargs)
        return {
            "par": "1",
            "id": 1,
            "title": "mcp retry",
            "project": "project",
            "request_key": "request-key-0004",
            "replayed": True,
        }

    monkeypatch.setattr(mcp, "_api", fake_api)
    result = json.loads(
        await mcp.task_create(title="mcp retry", request_key="request-key-0004")
    )

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/tm/tasks"
    assert seen["kwargs"]["request_id"] == "request-key-0004"
    assert seen["kwargs"]["idempotency_key"] == "request-key-0004"
    assert result["request_key"] == "request-key-0004"
    assert result["replayed"] is True


@pytest.mark.asyncio
async def test_t5_http_fallback_generation_validation_and_status_authorization():
    from app.routes.tm import router

    _seed_project()
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        fallback_key = "a" * 32
        created = await client.post(
            "/api/tm/tasks",
            headers={"X-Request-ID": fallback_key},
            json={"project": "project", "title": "fallback key"},
        )
        assert created.status_code == 200
        assert created.json()["request_key"] == fallback_key

        status = await client.get(
            f"/api/tm/task-create-requests/{fallback_key}",
            params={"project": "project"},
        )
        assert status.status_code == 200
        assert status.json()["task_id"] == created.json()["id"]
        foreign = await client.get(
            f"/api/tm/task-create-requests/{fallback_key}",
            params={"project": "foreign"},
        )
        assert foreign.status_code in {403, 404}

        generated = await client.post(
            "/api/tm/tasks",
            json={"project": "project", "title": "generated compatibility key"},
        )
        assert generated.status_code == 200
        assert len(generated.json()["request_key"]) == 32

        invalid = await client.post(
            "/api/tm/tasks",
            headers={"Idempotency-Key": "short"},
            json={"project": "project", "title": "invalid key"},
        )
        assert invalid.status_code == 400
        assert invalid.json()["reason"] == "INVALID_IDEMPOTENCY_KEY"


@pytest.mark.asyncio
async def test_t5_canonical_http_replay_conflict_and_pending_crash_recovery(tmp_path):
    from app import tm

    store = _canonical_store(tmp_path)
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        first = _payload(await _create(
            "request-key-0006", title="canonical HTTP", project="orchestra",
        ))
        replay = _payload(await _create(
            "request-key-0006", title="canonical HTTP", project="orchestra",
        ))
        conflict = await _create(
            "request-key-0006", title="canonical different body", project="orchestra",
        )
        assert replay["task_id"] == first["task_id"]
        assert replay["replayed"] is True
        assert isinstance(conflict, JSONResponse)
        assert conflict.status_code == 409

        committed = store.task_create(
            project_id="orchestra",
            title="recover pending canonical",
            display_number=407,
            expected_head=store.canonical_head,
            request_key="request-key-0007",
        )
        assert committed["request_fingerprint"].startswith("sha256:")
        now = datetime.now(timezone.utc).isoformat()
        with tm._conn() as connection:
            connection.execute(
                "INSERT INTO tm_task_create_requests("
                "project_id,request_key,fingerprint,active_owner,generation,state,created_at,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    "orchestra",
                    "request-key-0007",
                    committed["request_fingerprint"],
                    "canonical",
                    3,
                    "PENDING",
                    now,
                    now,
                ),
            )
            connection.commit()

        recovered = _payload(await _create(
            "request-key-0007",
            title="recover pending canonical",
            project="orchestra",
        ))

    assert recovered["task_id"] == committed["task_id"]
    assert recovered["replayed"] is True
    with tm._conn() as connection:
        assert connection.execute(
            "SELECT count(*) FROM tm_tasks WHERE project_id='orchestra' AND par_number=407"
        ).fetchone()[0] == 1
        receipt = connection.execute(
            "SELECT state,task_id,par_number FROM tm_task_create_requests "
            "WHERE project_id='orchestra' AND request_key='request-key-0007'"
        ).fetchone()
    assert receipt["state"] == "MIRRORS_COMMITTED"
    assert receipt["task_id"] == committed["task_id"]
    assert receipt["par_number"] == 407


@pytest.mark.asyncio
async def test_t5_pending_without_active_task_returns_retry_after_instead_of_waiting():
    from app import tm

    entered = threading.Event()
    release = threading.Event()

    class BlockingCanonical:
        canonical_head = "canonical-head"
        projection_head = "canonical-head"

        def task_list(self, **_kwargs):
            return {"tasks": [], "count": 0, "next_display_number": 1}

        def task_create(self, **_kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test failed to release canonical create")
            return {
                "par": "1",
                "task_id": "canonical-task-1",
                "stable_id": "canonical-task-1",
                "title": "idempotent task",
                "project": "project",
                "price_rub": 0,
                "status": "new",
                "canonical_head": "canonical-head-2",
                "projection_head": "canonical-head-2",
            }

    _seed_project()
    with tm.ia_process_task_store_mode(store=BlockingCanonical(), mode="canonical"):
        first = asyncio.create_task(_create("request-key-0008"))
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(_create("request-key-0008"))
        done, _pending = await asyncio.wait({second}, timeout=1)
        release.set()
        await first
        second_result = await second

    assert second in done, "same-key retry waited behind the active create"
    assert isinstance(second_result, JSONResponse)
    assert second_result.status_code == 409
    assert second_result.headers["Retry-After"] == "1"
    assert _payload(second_result)["reason"] == "IDEMPOTENCY_REQUEST_PENDING"


def test_t5_canonical_store_recovers_same_deterministic_request_identity(tmp_path):
    from app.ia.task_store import TaskStore, build_migration_manifest
    from tests.test_knowledge_runtime_debt_361 import _task_projection_snapshot

    assert "request_key" in inspect.signature(TaskStore.task_create).parameters
    store = TaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(_task_projection_snapshot()))

    first = store.task_create(
        project_id="orchestra",
        title="canonical retry",
        display_number=406,
        expected_head=store.canonical_head,
        request_key="request-key-0005",
    )
    replay = store.task_create(
        project_id="orchestra",
        title="canonical retry",
        display_number=406,
        expected_head=store.canonical_head,
        request_key="request-key-0005",
    )

    assert replay["task_id"] == first["task_id"]
    assert replay["canonical_head"] == first["canonical_head"]
    assert replay["replayed"] is True
    assert len(store._states()) == 2
    event_ids = {
        path.stem for path in (tmp_path / "tasks").rglob("events/*.json")
    }
    assert len(event_ids) == 2
