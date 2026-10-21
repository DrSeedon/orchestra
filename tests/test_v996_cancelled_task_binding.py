"""V-996: a worker bound to a cancelled task must still be able to take new work."""

import subprocess
import uuid

import pytest

from tests.test_adhoc_switch import _branch, _row, db, git_repo, wt_root  # noqa: F401
from tests.task_seeds import create_task as seed_task


async def _deliver(db, sid):
    import app.manager as mgr

    manager = mgr.SessionManager()
    session = manager._hydrate_row(db.get_session(sid))
    await manager._auto_switch_before_delivery(session)
    return session


def _bound_worker(db, git_repo, wt, status):
    from app import tm

    scope = str(git_repo)
    with tm._conn() as conn:
        project = tm.ensure_project(conn, "project", scope=scope)
        project_id = project["id"] if isinstance(project, dict) else project
        task = seed_task(conn, project_id, "old task", status=status, par_number=830)
        ref = tm.public_task_ref(task)
    sid = str(uuid.uuid4())
    row = _row(sid, scope, wt.path, "task-830/worker")
    row.update(task_id=ref, needs_switch=0)
    db.save_session(row)
    return sid, ref


@pytest.mark.asyncio
async def test_cancelled_task_binding_is_dropped_on_next_delivery(git_repo, wt_root, db):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "830", base_branch="main")
    sid, _ = _bound_worker(db, git_repo, wt, "cancelled")

    session = await _deliver(db, sid)

    saved = db.get_session(sid)
    assert saved["task_id"] == "" and not saved["needs_switch"]
    assert saved["branch"].startswith("adhoc-") and _branch(wt.path) == saved["branch"]
    assert session.task_id == ""


@pytest.mark.asyncio
async def test_active_task_binding_is_left_alone(git_repo, wt_root, db):
    from app.workspace import create_worktree

    wt = create_worktree(str(git_repo), "worker", "830", base_branch="main")
    sid, ref = _bound_worker(db, git_repo, wt, "in_progress")

    await _deliver(db, sid)

    saved = db.get_session(sid)
    assert saved["task_id"] == ref and saved["branch"] == "task-830/worker"
    assert _branch(wt.path) == "task-830/worker"
