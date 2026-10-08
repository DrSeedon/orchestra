import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from tests.test_task_tracker_integration import (
    _init_db,
    _make_git_scope,
    _save_worker,
    _seed_project,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _taskless_adhoc_worker(monkeypatch, tmp_path, *, dirty=False, commit=False):
    from app import workspace

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    _seed_project(str(repo))
    wt = workspace.create_worktree(str(repo), "idle-worker", base_branch="main")
    _git(Path(wt.path), "branch", "-m", "adhoc-1800000000-1/idle-worker")
    if commit:
        path = Path(wt.path) / "worker.txt"
        path.write_text("unmerged\n", encoding="utf-8")
        _git(Path(wt.path), "add", "worker.txt")
        _git(Path(wt.path), "commit", "-m", "unmerged worker work")
    if dirty:
        (Path(wt.path) / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    _git(repo, "checkout", "main")
    (repo / "new-main.txt").write_text("latest main\n", encoding="utf-8")
    _git(repo, "add", "new-main.txt")
    _git(repo, "commit", "-m", "advance main")

    name = "idle-worker"
    _save_worker(
        session_id=name, task_id="", scope=str(repo), worktree_path=wt.path,
        branch="adhoc-1800000000-1/idle-worker",
    )
    target = SimpleNamespace(
        id=name, name=name, scope=str(repo), parent_name="orchestrator",
        task_id="", branch="adhoc-1800000000-1/idle-worker", base_branch="main",
        worktree_path=wt.path, needs_switch=False,
    )
    import app.routes.sessions as sessions_route

    monkeypatch.setattr(
        sessions_route.manager, "ensure_loaded", AsyncMock(return_value=target),
    )
    monkeypatch.setattr(
        sessions_route.manager, "ensure_loaded_any", AsyncMock(return_value=None),
    )
    deliver = AsyncMock()
    monkeypatch.setattr(sessions_route.manager, "send", deliver)
    return sessions_route, repo, wt, target, deliver


@pytest.mark.asyncio
async def test_taskless_send_assignment_starts_from_current_main(monkeypatch, tmp_path):
    from app.db import get_session

    routes, repo, wt, target, deliver = _taskless_adhoc_worker(monkeypatch, tmp_path)
    main_head = _git(repo, "rev-parse", "main")

    result = await routes.send_message(
        target.name,
        routes.SendRequest(
            scope=target.scope, sender="orchestrator", message="Implement next task",
        ),
    )

    assert not isinstance(result, JSONResponse)
    assigned = result["task"]
    assert _git(Path(wt.path), "branch", "--show-current") == (
        f"task-{assigned['par_number']}/{target.name}"
    )
    assert _git(Path(wt.path), "rev-parse", "HEAD") == main_head
    assert (Path(wt.path) / "new-main.txt").read_text(encoding="utf-8") == "latest main\n"
    assert get_session(target.id)["task_id"] == str(assigned["par_number"])
    deliver.assert_awaited_once()


@pytest.mark.parametrize(("dirty", "commit"), [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_taskless_send_refuses_to_move_branch_with_unlanded_work(
    monkeypatch, tmp_path, dirty, commit,
):
    from app import tm
    from app.db import get_session

    routes, repo, wt, target, deliver = _taskless_adhoc_worker(
        monkeypatch, tmp_path, dirty=dirty, commit=commit,
    )
    branch = _git(Path(wt.path), "branch", "--show-current")
    head = _git(Path(wt.path), "rev-parse", "HEAD")

    result = await routes.send_message(
        target.name,
        routes.SendRequest(
            scope=target.scope, sender="orchestrator", message="Implement next task",
        ),
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 409
    assert "base is stale" in result.body.decode().lower()
    assert _git(Path(wt.path), "branch", "--show-current") == branch
    assert _git(Path(wt.path), "rev-parse", "HEAD") == head
    assert get_session(target.id)["task_id"] == ""
    with tm._conn() as connection:
        rows = connection.execute(
            "SELECT status, worker_session_id FROM tm_tasks",
        ).fetchall()
    assert [(row["status"], row["worker_session_id"]) for row in rows] == [
        ("new", None),
    ]
    deliver.assert_not_awaited()
