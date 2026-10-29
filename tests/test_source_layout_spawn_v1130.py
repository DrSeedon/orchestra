"""Offline real-Git spawn prerequisites, through the normal HTTP/MCP adapters."""

import json
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout


def snapshot(repo):
    return (
        git(repo, "show-ref"), git(repo, "status", "--porcelain=v1"),
        git(repo, "worktree", "list", "--porcelain"), git(repo, "stash", "list"),
        {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*")
         if ".git" not in p.relative_to(repo).parts and p.is_file()},
    )


@pytest.fixture
def env(tmp_path, monkeypatch, configured_hub):
    from app import db, manager as mm, mcp_stdio as m, pipeline
    from app.routes import sessions as routes
    from app.session import AgentSession

    db.init_db()
    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "source.txt").write_text("public synthetic source\n")
    (repo / "AGENTS.md").write_text("Synthetic repository; edit source.txt.\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Synthetic Test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "source snapshot")
    # Keep source, Git, prompt memory, publication and HTTP errors real. Only
    # provider startup is replaced: this test must never make a model call.
    start = AsyncMock()
    monkeypatch.setattr(AgentSession, "start", start)
    mgr = mm.SessionManager()
    monkeypatch.setattr(routes, "manager", mgr)
    monkeypatch.setattr("app.routes.system._is_safe_path", lambda _: True)
    pipeline.load_pipeline.cache_clear()
    monkeypatch.setattr(m, "SCOPE", str(repo))
    monkeypatch.setattr(m, "WORKER_NAME", "parent")
    create_worktree = MagicMock(wraps=mm.create_worktree)
    monkeypatch.setattr(mm, "create_worktree", create_worktree)
    from app import tm
    with tm._conn() as conn:
        tm.ensure_project(conn, "synthetic", scope=str(repo))
    allocate_task = MagicMock(wraps=tm.create_task_for_scope)
    monkeypatch.setattr(tm, "create_task_for_scope", allocate_task)
    app = FastAPI()
    app.include_router(routes.router)
    calls = []

    async def request(method, path, **kwargs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test.invalid",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def api(method, path, **kwargs):
        calls.append((method, path))
        response = await request(method, path, json=kwargs.get("json"))
        payload = response.json()
        if response.status_code >= 400:
            raise m._response_error(method, path, response, payload, "synthetic-request")
        return payload

    monkeypatch.setattr(m, "_api", api)
    yield SimpleNamespace(
        repo=repo, db=db, mgr=mgr, m=m, request=request, calls=calls,
        create_worktree=create_worktree, allocate_task=allocate_task, start=start,
    )
    pipeline.load_pipeline.cache_clear()


def add_state(env, path):
    target = env.repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("synthetic state\n")
    git(env.repo, "add", ".")
    git(env.repo, "commit", "-qm", "public state snapshot")


async def create(env, **changes):
    body = dict(
        name="w", cwd=str(env.repo), scope=str(env.repo), repo_path=str(env.repo),
        use_worktree=True, model="hubsol", parent_name="parent", role="worker",
        planned_initial_turn=True, initial_task_title="Synthetic task",
    )
    body.update(changes)
    return await env.request("POST", "/api/sessions", json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["hubsol", "hubopus"])
@pytest.mark.parametrize("reports", [False, True])
async def test_fresh_source_starts_without_layout_or_migration(env, model, reports):
    if reports:
        add_state(env, ".orchestra/tasks/result.md")
    before = git(env.repo, "rev-parse", "HEAD")
    response = await create(env, model=model, model_reason="Synthetic model parity check")
    assert response.status_code == 201, response.text
    assert len(env.db.get_all_sessions(str(env.repo))) == 1
    assert env.allocate_task.call_count == env.create_worktree.call_count == 1
    env.start.assert_awaited_once()
    assert git(env.repo, "rev-parse", "HEAD") == before
    assert not (env.repo / ".orchestra/layout.json").exists()
    for root in (env.repo, Path(response.json()["worktree_path"])):
        assert not (root / ".orchestra/private").exists()
        assert not (root / ".orchestra/.gitignore").exists()
    assert git(env.repo, "status", "--porcelain=v1") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["hubsol", "hubopus"])
@pytest.mark.parametrize("path", [
    ".orchestra/workers/w.md", "docs/workers/w.md",
    ".orchestra/.layout-migration.json", ".orchestra/unknown/keep.md",
])
async def test_layout_prerequisite_refuses_before_any_allocation(env, model, path):
    add_state(env, path)
    before = snapshot(env.repo)
    for _ in range(2):
        with pytest.raises(env.m.ApiToolError) as caught:
            await env.m.spawn_worker(
                name="w", task="Synthetic task", repo_path=str(env.repo), model=model,
                model_reason="Synthetic model parity check",
                delivery_id="11111111-1111-4111-8111-111111111111",
            )
        error = caught.value
        assert "ORCHESTRA_LAYOUT_MISSING" in error.message
        assert "migrate_orchestra_layout.py --repair" in error.message
        assert error.status == 409
        assert error.outcome_unknown is False
        assert error.retryable is False
    assert env.calls == [("POST", "/api/sessions")] * 2
    env.allocate_task.assert_not_called()
    env.create_worktree.assert_not_called()
    env.start.assert_not_awaited()
    assert env.mgr.sessions == {}
    assert env.db.get_all_sessions(str(env.repo)) == []
    with env.db._conn() as conn:
        assert conn.execute("SELECT count(*) FROM initial_deliveries").fetchone()[0] == 0
    assert snapshot(env.repo) == before


@pytest.mark.asyncio
async def test_explicit_task_refusal_preserves_task_and_ownership(env):
    from app import tm

    task = tm.create_task_for_scope(str(env.repo), "Existing task")
    env.allocate_task.reset_mock()
    task_ref = task.get("par") or str(task["par_number"])
    add_state(env, ".orchestra/workers/w.md")
    before = snapshot(env.repo)
    with env.db._conn() as conn:
        tasks_before = [dict(row) for row in conn.execute("SELECT * FROM tm_tasks")]
        reservations_before = [dict(row) for row in conn.execute("SELECT * FROM tm_task_reservations")]
    response = await create(env, task_id=task_ref, owned_dirs=["source.txt"])
    assert response.status_code == 409
    assert "ORCHESTRA_LAYOUT_MISSING" in response.text
    env.create_worktree.assert_not_called()
    env.allocate_task.assert_not_called()
    env.start.assert_not_awaited()
    with env.db._conn() as conn:
        assert [dict(row) for row in conn.execute("SELECT * FROM tm_tasks")] == tasks_before
        assert [dict(row) for row in conn.execute("SELECT * FROM tm_task_reservations")] == reservations_before
    assert env.db.get_all_sessions(str(env.repo)) == []
    assert snapshot(env.repo) == before


@pytest.mark.asyncio
async def test_supported_explicit_repair_then_spawn_keeps_memory(env):
    from app.orchestra_layout import LayoutMigrationError

    add_state(env, "docs/workers/w.md")
    assert (await create(env)).status_code == 409
    error = LayoutMigrationError("ORCHESTRA_LAYOUT_MISSING", env.repo, "synthetic prerequisite")
    repair = subprocess.run(
        shlex.split(error.repair_command), check=True, capture_output=True, text=True,
    )
    result = json.loads(repair.stdout)
    assert result["status"] == "repaired"
    assert result["ownership"]["changed"] == 0
    assert result["commit"] == git(env.repo, "rev-parse", "HEAD").strip()
    response = await create(env, owned_dirs=["source.txt"])
    assert response.status_code == 201, response.text
    session = next(iter(env.mgr.sessions.values()))
    assert "synthetic state" in session.system_prompt
    assert session.owned_dirs == ["source.txt"]
    assert not (env.repo / "docs/workers/w.md").exists()
    assert (env.repo / ".orchestra/workers/w.md").read_text() == "synthetic state\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse", [False, True])
async def test_selected_branch_with_layout_is_not_rejected_by_checkout_state(env, reuse):
    add_state(env, ".orchestra/workers/w.md")
    git(env.repo, "checkout", "-qb", "prepared")
    (env.repo / ".orchestra/layout.json").write_text(json.dumps({
        "schema_version": 1, "layout": ".orchestra", "managed_paths": ["workers"],
    }))
    git(env.repo, "add", ".")
    git(env.repo, "commit", "-qm", "prepared layout")
    changes = {"base_branch": "prepared"}
    if reuse:
        from app import tm
        task = tm.create_task_for_scope(str(env.repo), "Existing branch task")
        task_ref = task.get("par") or str(task["par_number"])
        from app.workspace import _worker_branch
        git(env.repo, "branch", _worker_branch(env.repo, "w", task_ref))
        changes = {"task_id": task_ref, "base_branch": "main"}
    git(env.repo, "checkout", "-q", "main")
    response = await create(env, **changes)
    assert response.status_code == 201, response.text
    assert "synthetic state" in next(iter(env.mgr.sessions.values())).system_prompt
    assert git(env.repo, "branch", "--show-current").strip() == "main"


@pytest.mark.asyncio
async def test_current_layout_and_historical_branch_keep_existing_migration(env):
    from app.orchestra_layout import migrate_project_layout

    # Keep the old branch's private link ignored when migration installs its
    # canonical unignore block (the same supported state as V-1031).
    (env.repo / ".gitignore").write_text(
        "# Orchestra project state is canonical Git data.\n!.orchestra/\n!.orchestra/**\n",
    )
    add_state(env, "docs/workers/w.md")
    git(env.repo, "branch", "old-worker")
    migrate_project_layout(env.repo)
    before = git(env.repo, "rev-parse", "HEAD")
    response = await create(env, base_branch="old-worker")
    assert response.status_code == 201, response.text
    assert "synthetic state" in next(iter(env.mgr.sessions.values())).system_prompt
    assert git(env.repo, "rev-parse", "HEAD") == before


@pytest.mark.asyncio
async def test_late_layout_error_and_unrelated_failure_remain_unknown(env, monkeypatch):
    from app.orchestra_layout import LayoutMigrationError

    for error in (
        LayoutMigrationError("ORCHESTRA_LAYOUT_MISSING", env.repo, "late change"),
        RuntimeError("synthetic unrelated preparation failure"),
    ):
        monkeypatch.setattr(env.mgr, "assemble_prompt", MagicMock(side_effect=error))
        with pytest.raises(env.m.ApiToolError) as caught:
            await env.m.spawn_worker(
                name="w", task="Synthetic task", repo_path=str(env.repo), model="hubsol",
            )
        assert caught.value.status == 500
        assert caught.value.outcome_unknown is True
    assert env.create_worktree.call_count == 2
    assert env.mgr.sessions == {}
    assert env.db.get_all_sessions(str(env.repo)) == []

