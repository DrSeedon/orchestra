"""Acceptance oracles for #248: make task state part of orchestration."""

import asyncio
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse


def _init_db():
    from app.db import init_db

    init_db()


def _seed_project(scope: str = "/scope") -> None:
    from app import tm

    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)


def _save_worker(
    *,
    session_id: str,
    task_id: str,
    scope: str = "/scope",
    worktree_path: str = "/worktree",
    branch: str = "",
    parent_name: str = "orchestrator",
) -> None:
    from app.db import save_session

    save_session({
        "id": session_id,
        "name": session_id,
        "scope": scope,
        "cwd": worktree_path,
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree_path,
        "branch": branch or f"task-{task_id or 'adhoc'}/{session_id}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": task_id,
        "is_orchestrator": False,
        "parent_name": parent_name,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })


@pytest.mark.asyncio
async def test_t1_planned_spawn_without_number_creates_and_binds_task(monkeypatch):
    """One spawn call must allocate the task number; the caller never invents it."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.manager import SessionManager
    from tests.conftest import make_backend_mock

    _init_db()
    _seed_project()
    local_manager = SessionManager()
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr("app.routes.system._is_safe_path", lambda _path: True)

    request = sessions_route.CreateSessionRequest(
        name="auto-number",
        scope="/scope",
        cwd="/tmp",
        model="claude-sonnet-5[1m]",
        role="worker",
        planned_initial_turn=True,
    ).model_copy(update={"initial_task_title": "Implement tracked feature"})

    with patch(
        "app.session.AgentSession._make_backend", return_value=make_backend_mock(),
    ):
        result = await sessions_route.create_session(request)

    assert not isinstance(result, JSONResponse)
    assert result["task_id"], "planned work must receive an auto-allocated task number"
    with tm._conn() as connection:
        task = tm.resolve_task_ref(connection, result["task_id"], "project")
    assert task is not None
    assert task["title"] == "Implement tracked feature"
    assert task["status"] == "in_progress"
    assert task["worker_session_id"] == result["id"]


@pytest.mark.asyncio
async def test_t1_taskless_assignment_replaces_made_up_number_with_canonical_task(
    monkeypatch,
):
    """The #243/#244 path allocates and binds a real number in the same call."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    _save_worker(session_id="taskless-worker", task_id="")
    target = SimpleNamespace(
        id="taskless-worker",
        name="taskless-worker",
        scope="/scope",
        parent_name="orchestrator",
        task_id="",
        role="worker",
        branch="feat/taskless-worker",
        base_branch="main",
        worktree_path="/worktree",
    )
    deliver = AsyncMock()
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded", AsyncMock(return_value=target))
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded_any", AsyncMock(return_value=None))
    monkeypatch.setattr(sessions_route.manager, "send", deliver)

    response = await sessions_route.send_message(
        "taskless-worker",
        sessions_route.SendRequest(
            scope="/scope", sender="orchestrator", message="#999: implement feature",
        ),
    )

    assert not isinstance(response, JSONResponse)
    task_state = response.get("task") or {}
    assert task_state.get("auto_created") is True
    assert str(task_state.get("par_number")) != "999"
    with tm._conn() as connection:
        task = tm.resolve_task_ref(
            connection, str(task_state["par_number"]), "project",
        )
    assert task is not None
    assert task["status"] == "in_progress"
    assert task["worker_session_id"] == target.id
    from app.db import get_session
    assert get_session(target.id)["task_id"] == str(task["par_number"])
    delivered = deliver.await_args.args[1]
    assert "#999:" not in delivered
    assert f"[Task #{task['par_number']}]" in delivered


@pytest.mark.asyncio
async def test_t1_taskless_assignment_is_parent_authorized_and_failure_atomic(monkeypatch):
    """Only the durable parent may assign; a failed branch switch delivers nothing."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    _save_worker(session_id="atomic-worker", task_id="")
    target = SimpleNamespace(
        id="atomic-worker",
        name="atomic-worker",
        scope="/scope",
        parent_name="orchestrator",
        task_id="",
        role="worker",
        branch="task-adhoc/atomic-worker",
        base_branch="main",
        worktree_path="/worktree",
    )
    deliver = AsyncMock()
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded", AsyncMock(return_value=target))
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded_any", AsyncMock(return_value=None))
    monkeypatch.setattr(sessions_route.manager, "send", deliver)

    with tm._conn() as connection:
        before = connection.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0]
    refused = await sessions_route.send_message(
        "atomic-worker",
        sessions_route.SendRequest(
            scope="/scope", sender="peer-worker", message="#999: steal assignment",
        ),
    )
    assert isinstance(refused, JSONResponse)
    assert refused.status_code in {403, 409}
    with tm._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == before
    deliver.assert_not_awaited()

    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        MagicMock(return_value={"ok": False, "error": "injected switch failure"}),
    )
    failed = await sessions_route.send_message(
        "atomic-worker",
        sessions_route.SendRequest(
            scope="/scope", sender="orchestrator", message="implement atomic assignment",
        ),
    )
    assert isinstance(failed, JSONResponse)
    assert failed.status_code >= 400
    assert get_session(target.id)["task_id"] == ""
    with tm._conn() as connection:
        rows = connection.execute(
            "SELECT status, worker_session_id FROM tm_tasks ORDER BY id",
        ).fetchall()
    assert [(row["status"], row["worker_session_id"]) for row in rows] == [("new", None)]
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_t1_bound_worker_rejects_conflicting_leading_task_number(monkeypatch):
    """A message cannot silently relabel a worker that is already bound to another task."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        tm.create_task(connection, "project", "Current", par_number=42)
    target = SimpleNamespace(
        id="bound-worker",
        name="bound-worker",
        scope="/scope",
        parent_name="orchestrator",
        task_id="42",
        role="worker",
    )
    deliver = AsyncMock()
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded", AsyncMock(return_value=target))
    monkeypatch.setattr(sessions_route.manager, "ensure_loaded_any", AsyncMock(return_value=None))
    monkeypatch.setattr(sessions_route.manager, "send", deliver)

    response = await sessions_route.send_message(
        "bound-worker",
        sessions_route.SendRequest(
            scope="/scope", sender="orchestrator", message="#999: unrelated work",
        ),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 409
    deliver.assert_not_awaited()


def _prepare_merge(monkeypatch, *, session_id: str, scope: str = "/scope"):
    import app.routes.sessions as sessions_route
    from app.manager import SessionManager

    local_manager = SessionManager()
    found = local_manager.get_by_name(session_id, scope)
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr(
        "app.workspace.classify_head_drift",
        lambda _path, branch, head: {
            "class": "SAME",
            "actual_branch": branch,
            "actual_head": head,
            "reason": "",
        },
    )
    monkeypatch.setattr(sessions_route, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr("app.rag_service.is_enabled", lambda: False)
    return found


def _make_git_scope(monkeypatch, tmp_path: Path) -> Path:
    """Create a real repository whose target ref can prove pre-commit refusal."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README.md").write_text("base")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True,
    )
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
    return repo


def _commit_file(worktree_path: str, filename: str, message: str) -> str:
    path = Path(worktree_path)
    (path / filename).write_text(message)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=path, check=True, capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path,
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.mark.asyncio
async def test_t2_bound_task_and_outcome_are_validated_before_git(monkeypatch):
    """Neither a made-up current task nor a missing disposition may reach Git."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        tm.create_task(connection, "project", "Real task", par_number=42)

    calls = []

    def merge(*_args, **_kwargs):
        calls.append("git")
        return {"ok": True, "commits_merged": 1, "merged_commits": {}}

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)

    _save_worker(session_id="missing-task", task_id="999")
    missing = _prepare_merge(monkeypatch, session_id="missing-task")
    result = await sessions_route.execute_merge_session(
        session_id=missing.id,
        expected_name=missing.name,
        expected_scope=missing.scope,
        expected_branch=missing.branch,
        expected_head="a" * 40,
        req={"scope": "/scope", "task_outcome": "complete", "merge_schema_version": 2},
    )
    assert calls == [], "a missing bound task must stop before the Git commit point"
    assert result["commit_point"] == "not_reached"

    _save_worker(session_id="missing-outcome", task_id="42")
    without_outcome = _prepare_merge(monkeypatch, session_id="missing-outcome")
    result = await sessions_route.execute_merge_session(
        session_id=without_outcome.id,
        expected_name=without_outcome.name,
        expected_scope=without_outcome.scope,
        expected_branch=without_outcome.branch,
        expected_head="b" * 40,
        req={"scope": "/scope", "merge_schema_version": 2},
    )
    assert calls == [], "a contentful task merge needs an explicit continue/complete outcome"
    assert result["commit_point"] == "not_reached"


@pytest.mark.asyncio
async def test_t2_merge_rejects_target_equal_worker_branch_before_git(monkeypatch):
    """A stale base pointing at the worker branch cannot close its bound task."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Bound task", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("self-target-worker", task["id"]),
        )
    _save_worker(session_id="self-target-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="self-target-worker")
    monkeypatch.setattr(
        sessions_route, "_session_base_branch", lambda *_args: found.branch,
    )
    merge = MagicMock()
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="a" * 40,
        req={
            "scope": "/scope",
            "task_outcome": "complete",
            "merge_schema_version": 2,
        },
    )

    assert result["ok"] is False
    assert result["commit_point"] == "not_reached"
    assert "worker branch" in result["error"]
    merge.assert_not_called()
    with tm._conn() as connection:
        unchanged = tm.get_task_by_id(connection, task["id"])
    assert (unchanged["status"], unchanged["worker_session_id"]) == (
        "in_progress", "self-target-worker",
    )
    assert get_session(found.id)["task_id"] == "42"


@pytest.mark.asyncio
async def test_t2_zero_commit_merge_does_not_close_task(monkeypatch):
    """A no-op merge is a failed pre-commit outcome, not a completed task."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "No-op task", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("noop-worker", task["id"]),
        )
    _save_worker(session_id="noop-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="noop-worker")
    merge = MagicMock(return_value={
        "ok": True,
        "commits_merged": 0,
        "branch": found.branch,
        "merged_commits": {},
        "target_before": "a" * 40,
        "target_after": "a" * 40,
    })
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="a" * 40,
        req={
            "scope": "/scope",
            "task_outcome": "complete",
            "merge_schema_version": 2,
        },
    )

    assert result["ok"] is False
    assert result["commit_point"] == "not_reached"
    assert result["code"] == "NO_COMMITS_MERGED"
    assert "no new commits" in result["error"]
    merge.assert_called_once()
    with tm._conn() as connection:
        unchanged = tm.get_task_by_id(connection, task["id"])
    assert unchanged["status"] == "in_progress"
    assert get_session(found.id)["task_id"] == "42"


@pytest.mark.asyncio
async def test_t2_unknown_commit_header_is_rejected_before_target_mutation(
    monkeypatch, tmp_path,
):
    """A real task binding cannot smuggle an unrelated made-up #N into main."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.workspace import create_worktree

    _init_db()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, check=True, capture_output=True,
    )
    (repo / "README.md").write_text("base")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True,
    )
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        tm.create_task(
            connection, "project", "Bound task", par_number=42, status="in_progress",
        )
    worktree = create_worktree(scope, "forged-header", task_id="42")
    (Path(worktree.path) / "work.txt").write_text("content")
    subprocess.run(
        ["git", "add", "."], cwd=worktree.path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "#999: fabricated assignment"],
        cwd=worktree.path, check=True, capture_output=True,
    )
    worker_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree.path,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    _save_worker(
        session_id="forged-header",
        task_id="42",
        scope=scope,
        worktree_path=worktree.path,
        branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="forged-header", scope=scope)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=worker_head,
        req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
    )

    target_after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert result["commit_point"] == "not_reached"
    assert target_after == target_before


@pytest.mark.asyncio
async def test_t2_all_candidate_refs_are_scoped_and_canonicalized(monkeypatch, tmp_path):
    """Multiple refs link in scope; a no-ref merge receives its bound primary ref."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.workspace import create_worktree

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        for number in (42, 44, 45):
            task = tm.create_task(
                connection, "project", f"Task {number}",
                par_number=number, status="in_progress",
            )
            if number in (42, 45):
                connection.execute(
                    "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
                    (f"worker-{number}", task["id"]),
                )

    multi = create_worktree(scope, "worker-42", task_id="42")
    _commit_file(multi.path, "one.txt", "first candidate")
    multi_head = _commit_file(multi.path, "two.txt", "#42, #44: linked candidate")
    _save_worker(
        session_id="worker-42", task_id="42", scope=scope,
        worktree_path=multi.path, branch=multi.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="worker-42", scope=scope)
    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=multi_head,
        req={"scope": scope, "task_outcome": "continue", "merge_schema_version": 2},
    )
    assert result["ok"] is True
    with tm._conn() as connection:
        additional = tm.resolve_task_ref(connection, "44", "project")
    assert json.loads(additional["git_commits"]), "every valid additional ref must link"

    no_ref = create_worktree(scope, "worker-45", task_id="45")
    no_ref_head = _commit_file(no_ref.path, "plain.txt", "plain unnumbered work")
    _save_worker(
        session_id="worker-45", task_id="45", scope=scope,
        worktree_path=no_ref.path, branch=no_ref.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="worker-45", scope=scope)
    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=no_ref_head,
        req={"scope": scope, "task_outcome": "continue", "merge_schema_version": 2},
    )
    assert result["ok"] is True
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert subject.startswith("#45:"), subject


@pytest.mark.asyncio
async def test_t2_repo_lock_recheck_rejects_substituted_or_foreign_ref(monkeypatch, tmp_path):
    """The final emitted header is revalidated under the lock against the pinned HEAD."""
    import app.routes.sessions as sessions_route
    from app import tm
    import app.workspace as workspace

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(
            connection, "project", "Bound", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?", ("substitute", task["id"]),
        )
        tm.ensure_project(connection, "foreign", scope="/foreign")
        tm.create_task(connection, "foreign", "Foreign", par_number=77)
    worktree = workspace.create_worktree(scope, "substitute", task_id="42")
    worker_head = _commit_file(worktree.path, "valid.txt", "#42: valid before lock")
    _save_worker(
        session_id="substitute", task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="substitute", scope=scope)
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    real_builder = workspace._build_squash_message
    monkeypatch.setattr(
        workspace,
        "_build_squash_message",
        lambda branch, messages: real_builder(branch, messages).replace("#42", "#77"),
    )

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=worker_head,
        req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
    )
    target_after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert result["commit_point"] == "not_reached"
    assert target_after == target_before


@pytest.mark.asyncio
async def test_t3_complete_merge_atomically_links_and_closes_current_task(monkeypatch):
    """A successful final merge, not a later task_update ritual, owns status=done."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Finish me", par_number=42,
            status="in_progress", price_rub=100,
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("complete-worker", task["id"]),
        )
    _save_worker(session_id="complete-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="complete-worker")
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "merged_commits": {
                "42": [{"hash": "abc123", "message": "#42: finish"}],
            },
        },
    )

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="c" * 40,
        req={"scope": "/scope", "task_outcome": "complete", "merge_schema_version": 2},
    )

    assert result["ok"] is True
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, task["id"])
    assert closed["status"] == "done"
    assert closed["worker_session_id"] is None
    assert closed["completed_at"]
    assert "abc123" in closed["git_commits"]


@pytest.mark.asyncio
async def test_t3_completion_reservation_blocks_a_concurrent_bind(monkeypatch):
    """Once complete reaches Git, no spawn may attach another live worker to the task."""
    import app.routes.sessions as sessions_route
    from app import tm
    from tests.conftest import make_backend_mock

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Serialized close", par_number=42,
            status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("closing-worker", task["id"]),
        )
    _save_worker(session_id="closing-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="closing-worker")
    entered_git = threading.Event()
    release_git = threading.Event()

    def slow_merge(*_args, **_kwargs):
        entered_git.set()
        assert release_git.wait(timeout=5)
        return {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "commit_point": "target_committed",
            "merged_commits": {
                "42": [{"hash": "race42", "message": "#42: close"}],
            },
        }

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", slow_merge)
    merge_task = asyncio.create_task(sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="f" * 40,
        req={"scope": "/scope", "task_outcome": "complete", "merge_schema_version": 2},
    ))
    assert await asyncio.to_thread(entered_git.wait, 5)

    monkeypatch.setattr("app.routes.system._is_safe_path", lambda _path: True)
    bind_request = sessions_route.CreateSessionRequest(
        name="late-binder",
        scope="/scope",
        cwd="/tmp",
        model="claude-sonnet-5[1m]",
        role="worker",
        task_id="42",
        planned_initial_turn=True,
    )
    try:
        with patch(
            "app.session.AgentSession._make_backend", return_value=make_backend_mock(),
        ):
            bind_result = await sessions_route.create_session(bind_request)
    finally:
        release_git.set()
    merge_result = await merge_task

    assert isinstance(bind_result, JSONResponse)
    assert bind_result.status_code == 409
    assert merge_result["ok"] is True
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, task["id"])
    assert closed["status"] == "done"
    assert closed["worker_session_id"] is None


@pytest.mark.asyncio
async def test_t3_complete_rejects_an_existing_second_live_binding_before_git(monkeypatch):
    """A task with another live worker cannot be declared complete by one merge."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Shared task", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("first-worker", task["id"]),
        )
    _save_worker(session_id="first-worker", task_id="42")
    _save_worker(session_id="second-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="first-worker")
    merge = MagicMock(return_value={"ok": True, "commits_merged": 1})
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="1" * 40,
        req={"scope": "/scope", "task_outcome": "complete", "merge_schema_version": 2},
    )

    assert result.get("commit_point") == "not_reached"
    merge.assert_not_called()


@pytest.mark.asyncio
async def test_t3_continue_merge_keeps_task_bound_on_fresh_branch(monkeypatch):
    """A research/plan merge is explicit continuation, never accidental done/quarantine."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Multi-phase", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("continue-worker", task["id"]),
        )
    _save_worker(session_id="continue-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="continue-worker")
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "merged_commits": {
                "42": [{"hash": "def456", "message": "#42: research"}],
            },
        },
    )
    switch = MagicMock(return_value={
        "ok": True, "branch": "task-42/continue-worker-2",
    })
    monkeypatch.setattr("app.workspace.switch_worktree_branch", switch)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="d" * 40,
        req={"scope": "/scope", "task_outcome": "continue", "merge_schema_version": 2},
    )

    assert result["ok"] is True
    with tm._conn() as connection:
        active = tm.get_task_by_id(connection, task["id"])
    assert active["status"] == "in_progress"
    assert active["worker_session_id"] == found.id
    lifecycle = get_session(found.id)
    assert lifecycle["task_id"] == "42"
    assert lifecycle["needs_switch"] == 0
    assert lifecycle["branch"].startswith("task-42/")


@pytest.mark.asyncio
async def test_t3_continue_rejects_next_task_before_git(monkeypatch):
    """Switching tasks is one complete transaction; continue cannot carry next_task_id."""
    import app.routes.sessions as sessions_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        current = tm.create_task(
            connection, "project", "Current", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("continue-next", current["id"]),
        )
        tm.create_task(connection, "project", "Next", par_number=43)
    _save_worker(session_id="continue-next", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="continue-next")
    merge = MagicMock(return_value={"ok": True, "commits_merged": 1})
    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="2" * 40,
        req={
            "scope": "/scope",
            "task_outcome": "continue",
            "next_task_id": "43",
            "merge_schema_version": 2,
        },
    )
    assert result.get("commit_point") == "not_reached"
    merge.assert_not_called()


@pytest.mark.asyncio
async def test_t3_complete_and_next_transition_is_one_atomic_finalizer(monkeypatch):
    """A successful handoff closes current and binds next without an intermediate taskless row."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        current = tm.create_task(
            connection, "project", "Current", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("handoff-worker", current["id"]),
        )
        next_task = tm.create_task(connection, "project", "Next", par_number=43)
    _save_worker(session_id="handoff-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="handoff-worker")
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "commit_point": "target_committed",
            "merged_commits": {
                "42": [{"hash": "handoff42", "message": "#42: finish current"}],
            },
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        MagicMock(return_value={"ok": True, "branch": "task-43/handoff-worker"}),
    )

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="4" * 40,
        req={
            "scope": "/scope",
            "task_outcome": "complete",
            "next_task_id": "43",
            "merge_schema_version": 2,
        },
    )

    assert result["ok"] is True
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, current["id"])
        active = tm.get_task_by_id(connection, next_task["id"])
    assert (closed["status"], closed["worker_session_id"]) == ("done", None)
    assert (active["status"], active["worker_session_id"]) == (
        "in_progress", "handoff-worker",
    )
    durable = get_session(found.id)
    assert (durable["task_id"], durable["needs_switch"]) == ("43", 0)


def test_t3_links_survive_late_finalizer_failure(monkeypatch):
    """Links committed before status work remain visible when that work raises."""
    from app import merge_operations as operations
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        first = tm.create_task(connection, "project", "First", par_number=590)
        second = tm.create_task(connection, "project", "Second", par_number=591)

    def fail_status_update(*_args, **_kwargs):
        raise RuntimeError("status stage exploded")

    monkeypatch.setattr(tm, "update_task", fail_status_update)
    finalization = {
        "project_id": "project",
        "task": {"task_id": first["id"]},
        "commits": {
            "590": [{"hash": "a" * 40, "message": "#590: first"}],
            "591": [{"hash": "b" * 40, "message": "#591: second"}],
        },
        "outcome": "complete",
        "reservation_id": "operation-398",
        "session_id": "worker-398",
    }

    with pytest.raises(RuntimeError, match="status stage exploded"):
        tm.finalize_merge_outcome(finalization)

    with tm._conn() as connection:
        linked = [
            tm.get_task_by_id(connection, task["id"])["git_commits"]
            for task in (first, second)
        ]
    assert all(json.loads(commits) for commits in linked)

    result = operations.normalize_merge_result(
        "operation-398",
        {
            "ok": False,
            "state": "partial",
            "commit_point": "target_committed",
            "error": "merge finalization failed: status stage exploded",
            "finalization": finalization,
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )
    assert result["task_links"]["status"] == "SUCCEEDED"
    assert set(result["task_links"]["items"]) == {"590", "591"}


@pytest.mark.asyncio
async def test_t3_switch_assignment_exception_rolls_back_branch_and_lifecycle(monkeypatch):
    """A binding exception compensates the Git switch instead of quarantining a dead worker."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session
    from app.manager import SessionManager

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Current", par_number=90, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("switch-exception-worker", task["id"]),
        )
    _save_worker(session_id="switch-exception-worker", task_id="90")
    local_manager = SessionManager()
    found = local_manager.get_by_name("switch-exception-worker", "/scope")
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr(sessions_route, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        sessions_route,
        "_existing_branch_verdict",
        lambda *_args, **_kwargs: {
            "recreate_from_base": False, "discard_current": False,
        },
    )
    monkeypatch.setattr(
        "app.tm.resolve_scoped_task_identity",
        lambda *_args: {
            "id": 91, "project_id": "project", "par_number": 91,
            "sync_revision": 0,
        },
    )
    switch_calls = []

    def fake_switch(_worktree, branch, from_ref="", force=False, **_kwargs):
        switch_calls.append((branch, from_ref, force))
        return {"ok": True, "branch": branch}

    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
    monkeypatch.setattr(
        "app.tm.api_update_task_if_current",
        MagicMock(side_effect=RuntimeError("injected binding failure")),
    )

    result = await sessions_route.switch_branch(
        "switch-exception-worker",
        {"scope": "/scope", "task_id": "91", "force": True},
    )

    assert result["ok"] is False
    assert result["state"] == "task_assignment_failed"
    assert result["rollback"]["ok"] is True
    assert [call[0] for call in switch_calls] == [
        "task-91/switch-exception-worker", "task-90/switch-exception-worker",
    ]
    row = get_session(found.id)
    assert (row["branch"], row["base_branch"], row["task_id"], row["needs_switch"]) == (
        "task-90/switch-exception-worker", "main", "90", 0,
    )


@pytest.mark.asyncio
async def test_t3_removing_last_worker_requeues_in_progress_task(monkeypatch):
    """Worker liveness is a platform fact; an archived last worker cannot stay active."""
    from app import tm
    from app.manager import SessionManager

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Interrupted", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("last-worker", task["id"]),
        )
    _save_worker(session_id="last-worker", task_id="42")
    manager = SessionManager()
    found = manager.get_by_name("last-worker", "/scope")
    found.worktree_path = ""
    manager.sessions[found.id] = found

    await manager.remove(found.id)

    with tm._conn() as connection:
        task = tm.get_task_by_id(connection, task["id"])
    assert task["status"] == "new"
    assert task["worker_session_id"] is None


@pytest.mark.asyncio
async def test_t3_removing_one_of_two_workers_preserves_active_task(monkeypatch):
    """Archive recomputes live bindings instead of blindly requeueing the task."""
    from app import tm
    from app.manager import SessionManager

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Still active", par_number=42,
            status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("leaving-worker", task["id"]),
        )
    _save_worker(session_id="leaving-worker", task_id="42")
    _save_worker(session_id="remaining-worker", task_id="42")
    manager = SessionManager()
    leaving = manager.get_by_name("leaving-worker", "/scope")
    leaving.worktree_path = ""
    manager.sessions[leaving.id] = leaving

    await manager.remove(leaving.id)

    with tm._conn() as connection:
        active = tm.get_task_by_id(connection, task["id"])
    assert active["status"] == "in_progress"
    assert active["worker_session_id"] == "remaining-worker"


@pytest.mark.asyncio
async def test_t3_merge_operation_replay_does_not_repeat_git_or_lose_task_outcome(
    monkeypatch,
):
    """A PARTIAL replay resumes only the durable DB finalizer, never Git."""
    import app.merge_operations as operations
    import app.routes.merge_operations as merge_route
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Durable close", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("durable-worker", task["id"]),
        )
    _save_worker(session_id="durable-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="durable-worker")
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: (found.branch, "e" * 40),
    )
    merge_calls = 0

    def merge(*_args, **_kwargs):
        nonlocal merge_calls
        merge_calls += 1
        return {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "commit_point": "target_committed",
            "merged_commits": {
                "42": [{"hash": "fedcba", "message": "#42: durable"}],
            },
        }

    monkeypatch.setattr("app.workspace.merge_worktree_to_main", merge)
    real_link = tm.link_commits_to_task
    link_attempts = 0

    def flaky_link(*args, **kwargs):
        nonlocal link_attempts
        link_attempts += 1
        if link_attempts == 1:
            raise RuntimeError("injected finalizer failure")
        return real_link(*args, **kwargs)

    monkeypatch.setattr(tm, "link_commits_to_task", flaky_link)
    operation_id = str(uuid.uuid4())
    request = {
        "operation_id": operation_id,
        "name": found.name,
        "scope": found.scope,
        "task_outcome": "complete",
        "merge_schema_version": 2,
    }

    await merge_route.create_merge_operation(request)
    await asyncio.gather(*list(operations._runner_tasks.values()))
    first = await merge_route.get_merge_operation(operation_id)
    partial = json.loads(first.body)["result"]

    assert partial["operation_state"] == "PARTIAL"
    assert partial["retryable"] is True
    finalization = partial["finalization"]
    assert finalization["stage"] == "PENDING"
    assert finalization["outcome"] == "complete"
    assert finalization["task"] == {
        "project_id": "project",
        "task_id": task["id"],
        "par_number": 42,
    }
    assert finalization["commits"] == {
        "42": [{"hash": "fedcba", "message": "#42: durable"}],
    }
    assert finalization["terminal_session"] == {"task_id": "", "needs_switch": True}
    assert finalization["next_task"] is None
    with tm._conn() as connection:
        still_open = tm.get_task_by_id(connection, task["id"])
    assert still_open["status"] == "in_progress"
    assert merge_calls == 1

    replay = await merge_route.create_merge_operation(request)
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))
    final = await merge_route.get_merge_operation(operation_id)
    payload = json.loads(final.body)["result"]

    assert payload["operation_state"] == "SUCCEEDED"
    assert payload["finalization"]["stage"] == "APPLIED"
    assert merge_calls == 1
    assert link_attempts == 2
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, task["id"])
    assert closed["status"] == "done"
    assert "fedcba" in closed["git_commits"]


@pytest.mark.asyncio
async def test_t3_first_post_git_checkpoint_loss_recovers_by_exact_trailer(
    monkeypatch, tmp_path,
):
    """Lose the first DB write after Git; same-id replay must recover without another merge."""
    import app.db as db
    import app.merge_operations as operations
    import app.routes.merge_operations as merge_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    operation_id = str(uuid.uuid4())
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(
            connection, "project", "Checkpoint recovery", par_number=42,
            status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("checkpoint-worker", task["id"]),
        )
    worktree = workspace.create_worktree(scope, "checkpoint-worker", task_id="42")
    _commit_file(worktree.path, "checkpoint.txt", "#42: checkpoint recovery")
    _save_worker(
        session_id="checkpoint-worker", task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id="checkpoint-worker", scope=scope)
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    real_merge = workspace.merge_worktree_to_main
    merge_calls = 0

    def counted_merge(*args, **kwargs):
        nonlocal merge_calls
        merge_calls += 1
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(workspace, "merge_worktree_to_main", counted_merge)
    real_conn = db._conn
    fault = {"fired": False, "sql": ""}

    def target_head() -> str:
        return subprocess.run(
            ["git", "rev-parse", "main"], cwd=repo,
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    class FailFirstPostGitWrite:
        def __init__(self):
            self.raw = real_conn()

        def __enter__(self):
            self.raw.__enter__()
            return self

        def __exit__(self, exc_type, exc, traceback):
            return self.raw.__exit__(exc_type, exc, traceback)

        def __getattr__(self, name):
            return getattr(self.raw, name)

        def execute(self, sql, parameters=()):
            normalized = " ".join(str(sql).upper().split())
            mutates = normalized.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE "))
            if not fault["fired"] and mutates and target_head() != target_before:
                fault.update(fired=True, sql=normalized)
                raise sqlite3.OperationalError("injected first post-Git checkpoint loss")
            return self.raw.execute(sql, parameters)

    def fault_conn():
        return FailFirstPostGitWrite()

    monkeypatch.setattr(db, "_conn", fault_conn)
    monkeypatch.setattr(tm, "_conn", fault_conn)
    monkeypatch.setattr(operations, "_conn", fault_conn)
    request = {
        "operation_id": operation_id,
        "name": found.name,
        "scope": found.scope,
        "task_outcome": "complete",
        "merge_schema_version": 2,
    }

    await merge_route.create_merge_operation(request)
    await asyncio.gather(*list(operations._runner_tasks.values()))
    first = await merge_route.get_merge_operation(operation_id)
    partial = json.loads(first.body)["result"]
    target_after = target_head()
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    body = subprocess.run(
        ["git", "log", "-1", "--format=%B", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout
    trailers = subprocess.run(
        ["git", "interpret-trailers", "--parse"], input=body,
        check=True, capture_output=True, text=True,
    ).stdout.strip().splitlines()
    parent = subprocess.run(
        ["git", "rev-parse", f"{target_after}^"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", f"{target_after}^{{tree}}"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    assert fault["fired"] is True
    assert "UPDATE MERGE_OPERATIONS" in fault["sql"]
    assert "COMMIT_POINT" in fault["sql"]
    assert "FINALIZATION_STAGE" in fault["sql"]
    assert partial["operation_state"] == "PARTIAL"
    assert partial["finalization"]["stage"] == "PENDING"
    assert partial["finalization"]["target_before"] == target_before
    assert partial["finalization"]["expected_tree"] == tree
    assert parent == target_before
    assert subject.startswith("#42:")
    assert trailers.count(f"Orchestra-Operation: {operation_id}") == 1
    assert merge_calls == 1
    assert subprocess.run(
        ["git", "rev-list", "--count", f"{target_before}..main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "1"

    await merge_route.create_merge_operation(request)
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))
    final = await merge_route.get_merge_operation(operation_id)
    payload = json.loads(final.body)["result"]
    assert payload["operation_state"] == "SUCCEEDED"
    assert payload["finalization"]["stage"] == "APPLIED"
    assert target_head() == target_after
    assert merge_calls == 1
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, task["id"])
    assert closed["status"] == "done"
    assert target_after[:7] in closed["git_commits"]

    replay = await merge_route.create_merge_operation(request)
    assert json.loads(replay.body)["result"]["operation_state"] == "SUCCEEDED"
    assert target_head() == target_after
    assert merge_calls == 1


@pytest.mark.asyncio
async def test_t3_new_merge_client_refuses_an_old_server_capability(monkeypatch):
    """New MCP schema never POSTs an outcome field to an operation-v1 server."""
    import app.mcp_stdio as mcp

    assert "task_outcome" in inspect.signature(mcp.merge_worker).parameters
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path == "/api/merge-operations/capabilities":
            return {"capability": "operation-v1", "schema_version": 1}
        raise AssertionError("new client must refuse before POST")

    monkeypatch.setattr(mcp, "_api", fake_api)
    output = await mcp.merge_worker(name="worker", task_outcome="complete")

    assert output.isError is True
    assert output.structuredContent["error"]["code"] == "MERGE_API_UPGRADE_REQUIRED"
    assert [(method, path) for method, path, _kwargs in calls] == [
        ("GET", "/api/merge-operations/capabilities"),
    ]


@pytest.mark.asyncio
async def test_t3_old_shape_merge_on_new_server_is_safe_legacy_continue(monkeypatch):
    """A surviving operation-v1 process may merge, but can never close a task implicitly."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "Legacy caller", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("legacy-worker", task["id"]),
        )
    _save_worker(session_id="legacy-worker", task_id="42")
    found = _prepare_merge(monkeypatch, session_id="legacy-worker")
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "commit_point": "target_committed",
            "merged_commits": {
                "42": [{"hash": "legacy42", "message": "#42: legacy"}],
            },
        },
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        MagicMock(return_value={"ok": True, "branch": "task-42/legacy-worker-2"}),
    )

    result = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head="3" * 40,
        req={"scope": "/scope"},
    )

    assert result["ok"] is True
    assert any(
        warning.get("code") == "LEGACY_MERGE_CONTINUE"
        for warning in result.get("warnings", [])
    )
    with tm._conn() as connection:
        active = tm.get_task_by_id(connection, task["id"])
    assert active["status"] == "in_progress"
    assert active["worker_session_id"] == found.id
    assert get_session(found.id)["task_id"] == "42"


@pytest.mark.asyncio
async def test_t3_agent_task_tools_cannot_override_platform_lifecycle(monkeypatch):
    """The old manual in_progress/done ritual is rejected at the agent tool boundary."""
    import app.mcp_stdio as mcp

    api = AsyncMock(return_value={})
    monkeypatch.setattr(mcp, "_api", api)

    with pytest.raises(mcp.ApiToolError) as update_error:
        await mcp.task_update("42", status="done")
    assert update_error.value.code == "lifecycle_platform_owned"

    with pytest.raises(mcp.ApiToolError) as create_error:
        await mcp.task_create("invalid shortcut", status="in_progress")
    assert create_error.value.code == "lifecycle_platform_owned"
    api.assert_not_awaited()


@pytest.mark.asyncio
async def test_t4_list_agents_carries_fresh_bounded_project_task_view(monkeypatch):
    """Reading tracker state piggybacks on list_agents: zero extra model round-trips."""
    import app.mcp_stdio as mcp

    monkeypatch.setattr(mcp, "SCOPE", "/scope")
    monkeypatch.setattr(mcp, "ROLE", "orchestrator")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")
    revision = {"title": "First title"}
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs.get("params")))
        if path == "/api/sessions":
            return [{
                "name": "worker",
                "role": "worker",
                "status": "idle",
                "model": "gpt-5.6-luna",
                "task_id": "7",
                "parent_name": "orchestrator",
            }]
        if path == "/api/role-icons":
            return {}
        if path == "/api/tm/tasks":
            return {
                "tasks": [
                    {"par_number": 7, "status": "in_progress", "priority": 1,
                     "title": revision["title"], "worker_session_id": "worker"},
                    {"par_number": 9, "status": "in_progress", "priority": 1,
                     "title": "Orphaned active", "worker_session_id": None},
                    *[
                        {"par_number": number, "status": "new", "priority": 2,
                         "title": f"Queued {number}", "worker_session_id": None}
                        for number in range(20, 5, -1)
                    ],
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr(mcp, "_api", fake_api)
    first = await mcp.list_agents()
    revision["title"] = "Second title"
    second = await mcp.list_agents()

    assert "#7 [in_progress] First title" in first
    assert "#7 [in_progress] Second title" in second
    assert "First title" not in second
    assert "#9 [in_progress] Orphaned active" in second
    assert second.count("[new]") <= 5
    assert len(second) <= 2_000
    assert [path for _method, path, _params in calls].count("/api/tm/tasks") == 2


def test_t4_task_prompt_delivers_automatic_lifecycle_without_manual_round_trips():
    """Delivery check: roles receive the new ownership boundary, not a prose-only edit."""
    from app.pipeline import build_system_prompt
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(
            connection, "project", "PROMPT_SNAPSHOT_FIRST", par_number=4248,
        )

    orchestrator = build_system_prompt("default", "orchestrator")
    full_cycle = build_system_prompt("default", "full-cycle")
    worker = build_system_prompt("default", "worker")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET title=? WHERE id=?",
            ("PROMPT_SNAPSHOT_SECOND", task["id"]),
        )
    rebuilt = build_system_prompt("default", "orchestrator")

    for prompt in (orchestrator, full_cycle):
        assert "Starting work** → `task_update" not in prompt
        assert "Successful merge** → `task_update" not in prompt
        assert "spawn/send/merge responses carry the fresh task state" in prompt
    assert "spawn/send/merge responses carry the fresh task state" not in worker
    for prompt in (orchestrator, rebuilt):
        assert "PROMPT_SNAPSHOT_FIRST" not in prompt
        assert "PROMPT_SNAPSHOT_SECOND" not in prompt
