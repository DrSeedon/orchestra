"""A running taskless worker can adopt its existing task without moving any WIP."""

import asyncio
import json
import subprocess
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from tests.task_seeds import create_task as seed_task
from tests.test_task_tracker_integration import (
    _commit_file, _init_db, _make_git_scope, _save_worker,
)


@pytest.fixture
def unbound_work(monkeypatch, tmp_path):
    from app import db, tm, workspace
    from app.manager import SessionManager
    from app.mcp_proof import issue_mcp_proof
    from app.session import AgentSession, AgentStatus
    import app.routes.sessions as route

    _init_db()
    monkeypatch.setenv("ORCHESTRA_TASK_PREFIX", "V-")
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        task = seed_task(conn, "project", "Existing task", par_number=251)
    tree = workspace.create_worktree(scope, "fixture-worker")
    tree.branch = "adhoc-1800000000-1/fixture-worker"
    subprocess.run(
        ["git", "branch", "-m", tree.branch], cwd=tree.path, check=True, capture_output=True,
    )
    heads = [
        _commit_file(tree.path, f"work-{i}.txt", f"#V-251: existing work {i}")
        for i in range(6)
    ]
    dirty = Path(tree.path, "unfinished.py")
    dirty.write_bytes(b"unfinished = True\n")
    _save_worker(
        session_id="fixture-worker", task_id="", scope=scope,
        worktree_path=tree.path, branch=tree.branch,
    )
    _save_worker(
        session_id="orchestrator", task_id="", scope=scope,
        worktree_path=str(repo), branch="main", parent_name="",
    )
    with db._conn() as conn:
        conn.execute("UPDATE sessions SET status='running' WHERE id='fixture-worker'")
    manager = SessionManager()
    live = AgentSession(
        id="fixture-worker", name="fixture-worker", scope=scope, cwd=tree.path,
        worktree_path=tree.path, branch=tree.branch, base_branch="main",
        parent_name="orchestrator",
    )
    live.status = AgentStatus.RUNNING
    manager.sessions[live.id] = live
    monkeypatch.setattr(route, "manager", manager)
    proof = issue_mcp_proof("orchestrator")
    request = Request({"type": "http", "headers": [
        (b"x-orchestra-session-id", b"orchestrator"),
        (b"x-orchestra-mcp-proof", proof.encode()),
    ]})
    return SimpleNamespace(
        repo=repo, scope=scope, tree=tree, heads=heads, dirty=dirty,
        task=task, live=live, request=request,
    )


def _git_snapshot(work):
    commands = [
        ["rev-parse", "HEAD"], ["branch", "--show-current"],
        ["status", "--porcelain=v1", "-z"], ["diff"], ["diff", "--cached"],
        ["log", "--format=%H"],
    ]
    return [subprocess.check_output(["git", *args], cwd=work.tree.path) for args in commands]


@pytest.mark.asyncio
async def test_mcp_binds_running_dirty_worker_to_existing_prefixed_task(unbound_work, monkeypatch):
    from app import db, tm, workspace
    from app.work_review import assignment
    import app.mcp_stdio as mcp
    import app.routes.sessions as route

    work = unbound_work
    before = _git_snapshot(work)
    assert tm.api_get_task("V-251", "project")["status"] == "new"
    assert tm.api_get_task("V-251", "project")["commits"] == []
    assert db.get_session(work.live.id)["task_id"] == ""
    assert len(workspace.branch_wip_status(work.tree.path, "main")["unmerged_commits"]) == 6
    assert assignment(work.scope, work.live.id, "V-251") is None
    monkeypatch.setattr(mcp, "SCOPE", work.scope)

    async def api(method, path, **kwargs):
        assert (method, path) == ("POST", "/api/sessions/fixture-worker/bind-task")
        response = await route.bind_worker_task(
            "fixture-worker", route.BindTaskRequest(**kwargs["json"]), work.request,
        )
        assert not isinstance(response, JSONResponse), getattr(response, "body", None)
        return response

    monkeypatch.setattr(mcp, "_api", api)
    for _ in range(2):
        result = json.loads(await mcp.bind_worker_task("fixture-worker", "V-251"))
        assert result["ok"] is True
        assert result["task"]["worker_session_id"] == work.live.id
        assert result["task"]["auto_created"] is False
    assert _git_snapshot(work) == before
    assert work.dirty.read_bytes() == b"unfinished = True\n"
    durable = db.get_session(work.live.id)
    assert (durable["task_id"], durable["status"], durable["branch"]) == (
        "V-251", "running", work.tree.branch,
    )
    assert work.live.task_id == "V-251"
    assert work.live.status.value == "running"
    task = tm.api_get_task("V-251", "project")
    assert task["id"] == work.task["id"]
    assert task["status"] == "in_progress"
    assert {c["hash"] for c in task["commits"]} == {h[:7] for h in work.heads}
    assert assignment(work.scope, work.live.id, "V-251")["status"] == "requested"
    work.live._persist()
    await work.live._drain_persist()
    assert db.get_session(work.live.id)["task_id"] == "V-251"
    # Canonical Git-backed task state survives projection refresh/restart.
    tm.active_runtime().refresh()
    assert tm.api_get_task("V-251", "project")["status"] == "in_progress"
    canonical = tm.active_runtime().store.get("project", "V-251")
    assert canonical["status"] == "in_progress"
    assert {c["hash"] for c in canonical["git_commits"]} == {h[:7] for h in work.heads}
    with tm._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM review_receipts WHERE subject_kind='task_run'",
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_binding_drains_pending_taskless_snapshot(unbound_work, monkeypatch):
    from app import db, tm
    import app.routes.sessions as route
    import app.session as session

    work = unbound_work
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    save = session.save_session
    bind = tm.bind_task_to_session
    loop_thread = threading.get_ident()
    drain = work.live._drain_persist
    draining = asyncio.Event()

    async def drain_pending():
        draining.set()
        await drain()

    def delayed_save(snapshot):
        started.set()
        assert release.wait(5), "pending session save was not released"
        save(snapshot)
        finished.set()

    def bind_after_save(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "binding blocked the event loop"
        assert finished.is_set(), "binding raced an older taskless snapshot"
        return bind(*args, **kwargs)

    monkeypatch.setattr(session, "save_session", delayed_save)
    monkeypatch.setattr(tm, "bind_task_to_session", bind_after_save)
    monkeypatch.setattr(work.live, "_drain_persist", drain_pending)
    work.live._persist()
    assert await asyncio.to_thread(started.wait, 5)
    pending = asyncio.create_task(route.bind_worker_task(
        work.live.name, route.BindTaskRequest(scope=work.scope, task_id="V-251"), work.request,
    ))
    try:
        await asyncio.wait_for(draining.wait(), 5)
    finally:
        release.set()
    result = await pending
    assert result["ok"] is True
    assert db.get_session(work.live.id)["task_id"] == "V-251"
    assert work.live.task_id == "V-251"


@pytest.mark.asyncio
async def test_bound_adhoc_work_can_finish_through_normal_merge(unbound_work, monkeypatch):
    from app import tm
    from app.session import AgentStatus
    import app.merge_operations as ops
    import app.routes.sessions as route

    work = unbound_work
    result = await route.bind_worker_task(
        work.live.name, route.BindTaskRequest(scope=work.scope, task_id="V-251"), work.request,
    )
    assert result["ok"] is True
    head = _commit_file(work.tree.path, work.dirty.name, "#V-251: finish existing WIP")
    work.live.status = AgentStatus.IDLE
    work.live._persist()
    await work.live._drain_persist()
    monkeypatch.setattr(ops, "ensure_operation_runner", lambda *_: None)
    accepted, status = await ops.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name=work.live.name, scope=work.scope,
        expected_head=head, acceptance_note="Inspected the complete existing task work.",
        accepting_actor="owner", task_outcome="complete", merge_schema_version=2,
    )
    assert status == 202, accepted
    await ops._run_operation(accepted["operation_id"])
    final = ops.get_operation_result(accepted["operation_id"])
    assert final["operation_state"] == "SUCCEEDED", final
    assert (work.repo / work.dirty.name).is_file()
    assert tm.api_get_task("V-251", "project")["status"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [
    "wrong_scope", "wrong_parent", "no_proof", "worker_bound", "task_owned",
    "split_owner", "reserved", "completed", "needs_switch", "branch_changed",
    "foreign_task", "history_unavailable",
])
async def test_binding_refuses_conflicts_without_changing_wip(unbound_work, conflict):
    from app import db, tm
    from app.work_review import assignment
    import app.routes.sessions as route

    work = unbound_work
    request = work.request
    requested_scope = work.scope
    with tm._conn() as conn:
        if conflict == "wrong_scope":
            requested_scope += "/foreign"
        elif conflict == "wrong_parent":
            conn.execute("UPDATE sessions SET parent_name='other' WHERE id=?", (work.live.id,))
        elif conflict == "no_proof":
            request = Request({"type": "http", "headers": []})
        elif conflict == "worker_bound":
            seed_task(conn, "project", "Other work", par_number=252)
        elif conflict == "task_owned":
            conn.execute("UPDATE tm_tasks SET worker_session_id='other' WHERE id=?", (work.task["id"],))
        elif conflict == "split_owner":
            _save_worker(session_id="other", task_id="V-251", scope=work.scope)
        elif conflict == "reserved":
            conn.execute(
                "INSERT INTO tm_task_reservations (task_id, operation_id, kind, session_id, created_at) "
                "VALUES (?, 'merge-conflict', 'primary', 'other', 'now')", (work.task["id"],),
            )
        elif conflict == "completed":
            conn.execute("UPDATE tm_tasks SET status='done' WHERE id=?", (work.task["id"],))
        elif conflict == "needs_switch":
            conn.execute("UPDATE sessions SET needs_switch=1 WHERE id=?", (work.live.id,))
        elif conflict == "branch_changed":
            conn.execute("UPDATE sessions SET branch='other' WHERE id=?", (work.live.id,))
        elif conflict == "foreign_task":
            tm.ensure_project(conn, "foreign", scope=work.scope + "/foreign")
            seed_task(conn, "foreign", "Foreign work", par_number=253)
        elif conflict == "history_unavailable":
            conn.execute("UPDATE sessions SET base_branch='missing-ref' WHERE id=?", (work.live.id,))
    if conflict == "worker_bound":
        tm.bind_task_to_session(work.scope, work.live.id, "V-252")
    before = _git_snapshot(work)
    durable_before = db.get_session(work.live.id)
    with tm._conn() as conn:
        task_before = tm.get_task_by_id(conn, work.task["id"])
        count_before = conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0]
    response = await route.bind_worker_task(
        work.live.name, route.BindTaskRequest(
            scope=requested_scope, task_id="V-253" if conflict == "foreign_task" else "V-251",
        ), request,
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code in {403, 404, 409}
    assert _git_snapshot(work) == before
    assert work.dirty.read_bytes() == b"unfinished = True\n"
    assert db.get_session(work.live.id) == durable_before
    assert work.live.task_id == ""
    with tm._conn() as conn:
        assert tm.get_task_by_id(conn, work.task["id"]) == task_before
        assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == count_before
    assert assignment(work.scope, work.live.id, "V-251") is None
