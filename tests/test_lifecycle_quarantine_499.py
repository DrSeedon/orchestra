"""Frozen regression oracles for lifecycle quarantine visibility and repair (#499)."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from starlette.requests import Request


def _session_row(*, task_id: str = "") -> dict:
    return {
        "id": "quarantined-session",
        "name": "worker",
        "scope": "/scope",
        "cwd": "/worktree",
        "model": "gpt-5.6-luna",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": "task-90/worker",
        "base_branch": "main",
        "needs_switch": int(bool(task_id)),
        "task_id": task_id,
        "is_orchestrator": False,
        "parent_name": "orchestrator",
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/sessions/worker/send",
        "headers": [(b"cookie", b"session=test-operator")],
    })


@pytest.mark.asyncio
async def test_quarantined_delivery_is_refused_before_accept_and_wip_is_loud(
    monkeypatch,
):
    """The incident was a successful QUEUED receipt plus an idle/clean WIP report."""
    from app import db, message_deliveries, tm
    from app.manager import SessionManager
    from app.routes import sessions as routes
    import app.auth as auth
    import app.mcp_stdio as mcp
    import app.workspace as workspace

    db.init_db()
    db.save_session(_session_row())
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        tm.create_task(connection, "project", "Interrupted task", par_number=90)
    tm.bind_task_to_session("/scope", "quarantined-session", "90")

    local_manager = SessionManager()
    monkeypatch.setattr(routes, "manager", local_manager)
    found = local_manager.get_by_name("worker", "/scope")
    await routes._persist_lifecycle_quarantine(
        found,
        branch="task-90/worker",
        base_branch="main",
        task_id="90",
        needs_switch=True,
    )
    found.loaded = True
    found._display_status = lambda: "idle"
    local_manager.sessions[found.id] = found
    monkeypatch.setattr(auth, "validate_session", lambda _cookie: True)
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target_id: None)
    monkeypatch.setattr(routes, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        workspace,
        "branch_wip_status",
        lambda *_args, **_kwargs: {
            "uncommitted": [],
            "unmerged_commits": [],
            "changed_files": [],
            "base_ref": "main",
        },
    )
    monkeypatch.setattr(mcp, "SCOPE", "/scope")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")

    async def route_api(method, path, *, json=None, params=None, **_kwargs):
        if method == "POST":
            response = await routes.send_message(
                "worker", routes.SendRequest(**json), request=_request(),
            )
        else:
            response = await routes.session_wip(
                "worker", scope=(params or {}).get("scope", ""),
                base_ref=(params or {}).get("base_ref", ""),
            )
        if isinstance(response, dict):
            return response
        body = json_module.loads(response.body)
        if response.status_code >= 400:
            error = body.get("error") or {}
            if isinstance(error, str):
                error = {"code": "http_error", "message": error}
            raise mcp.ApiToolError(
                code=error.get("code", "http_error"),
                message=error.get("message", "request failed"),
                status=response.status_code,
                retryable=bool(error.get("retryable", False)),
                outcome_unknown=bool(error.get("outcome_unknown", False)),
                details=error.get("details") or {},
            )
        return body

    json_module = json
    monkeypatch.setattr(mcp, "_api", route_api)
    delivery_id = str(uuid.uuid4())
    try:
        delivery = await mcp.send_message(
            to="worker", message="next task", delivery_id=delivery_id,
        )
    except mcp.ApiToolError as error:
        delivery = f"ERROR {error.code}: {error.message}"
    wip = await mcp.worker_wip(name="worker")

    print(f"DELIVERY_RESULT={delivery}")
    print(f"WIP_RESULT={wip}")
    assert "LIFECYCLE_QUARANTINED" in delivery
    assert "switch_worker_branch" in delivery
    assert "quarantined" in wip.lower()


def test_unrelated_interference_converges_but_same_task_contention_loses(tmp_path):
    from app.ia.task_store import TaskStore, build_migration_manifest
    from tests.test_knowledge_runtime_debt_361 import _task_projection_snapshot

    snapshot = _task_projection_snapshot()
    snapshot["projects"][0].update(id="project", scope="/scope")
    first = snapshot["tasks"][0]
    first.update(id=1, project_id="project", par_number=104, title="repair target")
    snapshot["tasks"].append({
        **first, "id": 2, "par_number": 105, "title": "unrelated task",
    })
    class InterferingTaskStore(TaskStore):
        interfere_with_same_task = False

        @property
        def canonical_head(self):
            if self.interfere_with_same_task:
                self.interfere_with_same_task = False
                self.task_update(
                    "105", project="project", title="genuine concurrent update",
                    expected_head=self._current_head(),
                )
            return self._current_head()

    store = InterferingTaskStore(
        canonical_root=tmp_path / "tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(snapshot))

    target = store.task_get("104", project="project")
    target_identity = {
        "project_id": "project",
        "par_number": 104,
        "stable_id": target["stable_id"],
        "sync_revision": target["sync_revision"],
    }
    historical_head = target["canonical_head"]
    store.task_update(
        "105", project="project", title="unrelated task advanced",
        expected_head=store.canonical_head,
    )
    advanced_head = store.canonical_head
    assert historical_head != advanced_head

    unrelated_result = store.task_update_if_current(
        target_identity, status="in_progress",
    )
    assert unrelated_result["ok"] is True

    same_target = store.task_get("105", project="project")
    same_identity = {
        "project_id": "project",
        "par_number": 105,
        "stable_id": same_target["stable_id"],
        "sync_revision": same_target["sync_revision"],
    }
    store.interfere_with_same_task = True
    contention_result = store.task_update_if_current(
        same_identity, status="in_progress",
    )

    print(f"UNRELATED_INTERFERENCE={unrelated_result['ok']}")
    print(f"SAME_TASK_CONTENTION={contention_result}")
    assert contention_result == {
        "ok": False,
        "error": "prevalidated task revision changed",
    }


@pytest.mark.asyncio
async def test_one_predicate_drives_list_wip_and_delivery_together(
    tmp_path, monkeypatch,
):
    from app import db, message_deliveries, tm
    from app.manager import LifecycleQuarantineError, SessionManager
    from app.routes import sessions as routes
    import app.auth as auth
    import app.mcp_stdio as mcp
    import app.workspace as workspace

    db.init_db()
    row = _session_row()
    row["worktree_path"] = str(tmp_path)
    row["cwd"] = str(tmp_path)
    db.save_session(row)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        tm.create_task(connection, "project", "Interrupted task", par_number=90)
    tm.bind_task_to_session("/scope", "quarantined-session", "90")
    db.update_session_lifecycle(
        "quarantined-session",
        branch="task-90/worker",
        base_branch="main",
        task_id="90",
        needs_switch=True,
    )

    local_manager = SessionManager()
    found = local_manager.get_by_name("worker", "/scope")
    found.loaded = True
    local_manager.sessions[found.id] = found
    monkeypatch.setattr(routes, "manager", local_manager)
    monkeypatch.setattr(auth, "validate_session", lambda _cookie: True)
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _target_id: None)
    monkeypatch.setattr(routes, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        workspace,
        "branch_wip_status",
        lambda *_args, **_kwargs: {
            "uncommitted": [], "unmerged_commits": [], "changed_files": [],
            "base_ref": "main",
        },
    )

    async def derived_gate(session):
        lifecycle = local_manager.lifecycle_quarantine(session)
        if lifecycle:
            raise LifecycleQuarantineError(lifecycle)

    monkeypatch.setattr(local_manager, "_auto_switch_before_delivery", derived_gate)
    monkeypatch.setattr(mcp, "SCOPE", "/scope")
    monkeypatch.setattr(mcp, "ROLE", "worker")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")
    monkeypatch.setattr(mcp, "PARENT_NAME", "orchestrator")

    async def route_api(method, path, *, json=None, params=None, **_kwargs):
        if path == "/api/sessions":
            return local_manager.list_sessions((params or {}).get("scope"))
        if path == "/api/role-icons":
            return {}
        if path.endswith("/wip"):
            response = await routes.session_wip(
                "worker", scope=(params or {}).get("scope", ""),
                base_ref=(params or {}).get("base_ref", ""),
            )
        else:
            response = await routes.send_message(
                "worker", routes.SendRequest(**json), request=_request(),
            )
        if isinstance(response, dict):
            return response
        body = json_module.loads(response.body)
        if response.status_code >= 400:
            error = body["error"]
            raise mcp.ApiToolError(
                code=error.get("code", "http_error"),
                message=error.get("message", "request failed"),
                status=response.status_code,
                retryable=bool(error.get("retryable", False)),
                outcome_unknown=bool(error.get("outcome_unknown", False)),
                details=error.get("details") or {},
            )
        return body

    json_module = json
    monkeypatch.setattr(mcp, "_api", route_api)

    async def observations():
        listed = await mcp.list_agents()
        wip = await mcp.worker_wip(name="worker")
        try:
            sent = await mcp.send_message(
                to="worker", message="probe", delivery_id=str(uuid.uuid4()),
            )
        except mcp.ApiToolError as error:
            sent = f"{error.code}: {error.message}"
        return listed, wip, sent

    monkeypatch.setattr(tm, "task_binding_requires_quarantine", lambda *_args: True)
    blocked = await observations()
    assert all("LIFECYCLE_QUARANTINED" in value for value in blocked)

    monkeypatch.setattr(tm, "task_binding_requires_quarantine", lambda *_args: False)
    allowed = await observations()
    assert all("LIFECYCLE_QUARANTINED" not in value for value in allowed)
    assert "Message accepted" in allowed[2]


@pytest.mark.asyncio
async def test_switch_repairs_current_binding_then_becomes_clean_noop(
    tmp_path, monkeypatch,
):
    from app import db, tm
    from app.manager import SessionManager
    from app.routes import sessions as routes

    db.init_db()
    row = _session_row()
    row["worktree_path"] = str(tmp_path)
    row["cwd"] = str(tmp_path)
    db.save_session(row)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        tm.create_task(connection, "project", "Interrupted task", par_number=90)
    tm.bind_task_to_session("/scope", "quarantined-session", "90")
    db.update_session_lifecycle(
        "quarantined-session",
        branch="task-90/worker",
        base_branch="main",
        task_id="90",
        needs_switch=True,
    )

    local_manager = SessionManager()
    monkeypatch.setattr(routes, "manager", local_manager)
    monkeypatch.setattr(
        routes, "_session_base_branch",
        lambda _session, requested="": requested or "main",
    )
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-90/worker", "a" * 40),
    )
    request = {"scope": "/scope", "task_id": "90", "from_ref": "release"}

    repaired = await routes.switch_branch("worker", request)
    repeated = await routes.switch_branch("worker", request)

    assert repaired["state"] == "lifecycle_repaired"
    assert repeated == {
        "ok": True,
        "state": "already_current",
        "branch": "task-90/worker",
        "waited_seconds": 0.0,
        "message": "task/branch binding is already healthy; no changes made",
    }
    saved = db.get_session("quarantined-session")
    assert saved["needs_switch"] == 0
    assert saved["task_id"] == "90"
    assert saved["base_branch"] == "main"


@pytest.mark.asyncio
async def test_healthy_delivery_and_status_remain_healthy(tmp_path, monkeypatch):
    from app import db, tm
    from app.manager import SessionManager

    db.init_db()
    row = _session_row(task_id="")
    row["worktree_path"] = str(tmp_path)
    row["cwd"] = str(tmp_path)
    db.save_session(row)
    manager = SessionManager()
    found = manager.get_by_name("worker", "/scope")
    found.loaded = True
    manager.sessions[found.id] = found

    await manager.preflight_message_delivery(found.id)
    listed = manager.list_sessions("/scope")

    assert listed[0]["status"] == "idle"
    assert "lifecycle_status" not in listed[0]
    assert tm.task_binding_requires_quarantine("/scope", found.id, "") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("lifecycle_repaired", "Repaired lifecycle binding"),
        ("already_current", "No-op: worker is already on healthy branch"),
    ],
)
async def test_switch_tool_reports_repair_and_idempotent_noop(
    state, expected, monkeypatch,
):
    import app.mcp_stdio as mcp

    async def fake_api(*_args, **_kwargs):
        return {"ok": True, "state": state, "branch": "task-90/worker"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    output = await mcp.switch_worker_branch("worker", "90", "main")
    assert expected in output


def test_legacy_merge_warning_names_the_exact_repair_call():
    from app.routes.sessions import _legacy_merge_continue_warning

    warning = _legacy_merge_continue_warning("worker", "90", "main")
    assert warning["code"] == "LEGACY_MERGE_CONTINUE"
    assert (
        'switch_worker_branch(name="worker", task_id="90", from_ref="main")'
        in warning["message"]
    )
    assert "idempotent" in warning["message"]


def _allocator_store(tmp_path):
    from app import db, tm
    from app.ia.task_store import TaskStore, build_migration_manifest
    from tests.test_knowledge_runtime_debt_361 import _task_projection_snapshot

    db.init_db()
    scope = str(tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(connection, "project", "existing", par_number=1)
    snapshot = _task_projection_snapshot()
    snapshot["projects"][0].update(id="project", scope=scope)
    snapshot["tasks"][0].update(
        id=task["id"], project_id="project", par_number=1, title="existing",
    )
    store = TaskStore(
        canonical_root=tmp_path / "canonical-tasks",
        projection_path=tmp_path / "task-current.db",
    )
    store.migrate(build_migration_manifest(snapshot))
    return scope, store


@pytest.mark.parametrize("request_key", ["", "request-key-499-gap"])
def test_shared_allocator_skips_surviving_artifact_directories(tmp_path, request_key):
    from app import tm

    scope, store = _allocator_store(tmp_path)
    artifacts = tmp_path / "repo" / ".orchestra" / "tasks"
    (artifacts / "2").mkdir(parents=True)
    (artifacts / "3").mkdir()

    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        created = tm.api_create_task(
            "project", "after artifact gap", scope=scope, request_key=request_key,
        )

    assert created["par"] == "4"
    assert store.task_get("4", project="project")["title"] == "after artifact gap"
    with tm._conn() as connection:
        numbers = [
            row[0] for row in connection.execute(
                "SELECT par_number FROM tm_tasks WHERE project_id='project' "
                "ORDER BY par_number"
            ).fetchall()
        ]
    assert numbers == [1, 4]


def test_shared_allocator_still_refuses_genuine_store_divergence(tmp_path):
    from app import tm
    from app.ia.task_store import IdentityConflictError

    scope, store = _allocator_store(tmp_path)
    artifacts = tmp_path / "repo" / ".orchestra" / "tasks"
    (artifacts / "2").mkdir(parents=True)
    (artifacts / "3").mkdir()
    with tm._conn() as connection:
        tm.create_task(connection, "project", "legacy-only", par_number=3)

    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        with pytest.raises(
            IdentityConflictError,
            match="task display counter mismatch.*canonical=2, legacy=4",
        ):
            tm.api_create_task("project", "must refuse", scope=scope)

    with pytest.raises(ValueError, match="2 not found"):
        store.task_get("2", project="project")
    with tm._conn() as connection:
        assert connection.execute(
            "SELECT count(*) FROM tm_tasks WHERE project_id='project'"
        ).fetchone()[0] == 2


@pytest.mark.asyncio
async def test_delivery_acceptance_holds_target_lock_until_receipt_commits(
    tmp_path, monkeypatch,
):
    from app import db, message_deliveries
    from app.manager import SessionManager
    from app.routes import sessions as routes
    import app.auth as auth

    db.init_db()
    row = _session_row(task_id="")
    row.update(worktree_path=str(tmp_path), cwd=str(tmp_path), needs_switch=0)
    db.save_session(row)
    manager = SessionManager()
    found = manager.get_by_name("worker", "/scope")
    found.loaded = True
    manager.sessions[found.id] = found
    monkeypatch.setattr(routes, "manager", manager)
    monkeypatch.setattr(auth, "validate_session", lambda _cookie: True)

    accept_entered = asyncio.Event()
    release_accept = asyncio.Event()
    repair_started = asyncio.Event()
    repair_entered = asyncio.Event()

    async def held_accept(**payload):
        accept_entered.set()
        await release_accept.wait()
        return ({
            "ok": True,
            "acceptance": "ACCEPTED",
            "delivery_id": payload["delivery_id"],
            "delivery_state": "QUEUED",
        }, 202)

    monkeypatch.setattr(message_deliveries, "accept_message_delivery", held_accept)
    send = asyncio.create_task(routes.send_message(
        "worker",
        routes.SendRequest(
            message="probe", scope="/scope", delivery_id=str(uuid.uuid4()),
        ),
        request=_request(),
    ))
    await accept_entered.wait()

    async def concurrent_repair():
        repair_started.set()
        async with manager.get_session_lock(found.id):
            repair_entered.set()

    repair = asyncio.create_task(concurrent_repair())
    await repair_started.wait()
    assert not repair_entered.is_set()
    release_accept.set()
    response = await send
    await repair

    assert response.status_code == 202
    assert repair_entered.is_set()


@pytest.mark.asyncio
async def test_same_task_repair_refuses_actual_worktree_drift(tmp_path, monkeypatch):
    from app import db, tm
    from app.manager import SessionManager
    from app.routes import sessions as routes

    db.init_db()
    row = _session_row()
    row.update(worktree_path=str(tmp_path), cwd=str(tmp_path))
    db.save_session(row)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        tm.create_task(connection, "project", "Interrupted task", par_number=90)
    tm.bind_task_to_session("/scope", "quarantined-session", "90")
    db.update_session_lifecycle(
        "quarantined-session", branch="task-90/worker", base_branch="main",
        task_id="90", needs_switch=True,
    )
    manager = SessionManager()
    monkeypatch.setattr(routes, "manager", manager)
    monkeypatch.setattr(routes, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-91/worker", "b" * 40),
    )

    response = await routes.switch_branch(
        "worker", {"scope": "/scope", "task_id": "90", "from_ref": "main"},
    )
    body = json.loads(response.body)

    assert response.status_code == 409
    assert "does not match actual branch task-91/worker" in body["error"]
    assert db.get_session("quarantined-session")["needs_switch"] == 1


@pytest.mark.asyncio
async def test_repair_persistence_failure_changes_neither_binding_owner(
    tmp_path, monkeypatch,
):
    from unittest.mock import AsyncMock

    from app import db, tm
    from app.manager import SessionManager
    from app.routes import sessions as routes

    db.init_db()
    row = _session_row()
    row.update(worktree_path=str(tmp_path), cwd=str(tmp_path))
    db.save_session(row)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(connection, "project", "Interrupted task", par_number=90)
    tm.bind_task_to_session("/scope", "quarantined-session", "90")
    db.update_session_lifecycle(
        "quarantined-session", branch="task-90/worker", base_branch="main",
        task_id="90", needs_switch=True,
    )
    with tm._conn() as connection:
        before = tm.get_task_by_id(connection, task["id"])

    manager = SessionManager()
    monkeypatch.setattr(routes, "manager", manager)
    monkeypatch.setattr(routes, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-90/worker", "a" * 40),
    )
    monkeypatch.setattr(
        manager, "transition_lifecycle",
        AsyncMock(side_effect=RuntimeError("DB unavailable")),
    )

    response = await routes.switch_branch(
        "worker", {"scope": "/scope", "task_id": "90", "from_ref": "main"},
    )
    with tm._conn() as connection:
        after = tm.get_task_by_id(connection, task["id"])

    assert response.status_code == 409
    assert (after["status"], after["worker_session_id"], after["sync_revision"]) == (
        before["status"], before["worker_session_id"], before["sync_revision"],
    )
    saved = db.get_session("quarantined-session")
    assert (saved["task_id"], saved["needs_switch"]) == ("90", 1)


@pytest.mark.asyncio
async def test_repair_refuses_to_create_a_missing_task_binding(tmp_path, monkeypatch):
    from app import db, tm
    from app.manager import SessionManager
    from app.routes import sessions as routes

    db.init_db()
    row = _session_row(task_id="90")
    row.update(worktree_path=str(tmp_path), cwd=str(tmp_path), needs_switch=1)
    db.save_session(row)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(connection, "project", "Unbound task", par_number=90)
    manager = SessionManager()
    monkeypatch.setattr(routes, "manager", manager)
    monkeypatch.setattr(routes, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-90/worker", "a" * 40),
    )

    response = await routes.switch_branch(
        "worker", {"scope": "/scope", "task_id": "90", "from_ref": "main"},
    )
    with tm._conn() as connection:
        unchanged = tm.get_task_by_id(connection, task["id"])

    assert response.status_code == 409
    assert unchanged["status"] == "new"
    assert unchanged["worker_session_id"] is None
    assert db.get_session("quarantined-session")["needs_switch"] == 1
