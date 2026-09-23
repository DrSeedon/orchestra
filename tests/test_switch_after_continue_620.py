"""V-620: a worker left on its task by merge(continue) must be switchable to a new task.

merge(continue) resets the worker branch onto the target and keeps the task run open.
With nothing left to merge, merge(complete) is refused, and switch_worker_branch used to
fail on the still-open run — the worker stayed bound forever. The switch now frees the
previous task when the worker has no unlanded work.
"""

import subprocess
from pathlib import Path

import pytest

from tests.task_seeds import create_task as seed_task
from tests.test_task_tracker_integration import (
    _commit_file,
    _init_db,
    _make_git_scope,
    _prepare_merge,
    _save_worker,
)


def _rev(cwd, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _runs(session_id: str) -> dict[str, dict]:
    from app import tm

    with tm._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM review_receipts WHERE subject_kind='task_run' AND session_id=?",
            (session_id,),
        ).fetchall()
    return {row["task_id"]: dict(row) for row in rows}


def _task(task_id: int) -> dict:
    from app import tm

    with tm._conn() as connection:
        return tm.get_task_by_id(connection, task_id)


async def _worker_after_continue(monkeypatch, tmp_path, name: str):
    """Real repo; task 5 bound with an open run, merged with `continue`; task 6 queued."""
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        current = seed_task(connection, "project", "Current", par_number=5)
        following = seed_task(connection, "project", "Next", par_number=6)
    current_ref = tm.public_task_ref(current)
    worktree = workspace.create_worktree(scope, name, task_id=current_ref)
    _save_worker(
        session_id=name, task_id=current_ref, scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    tm.bind_task_to_session(scope, name, current_ref)
    head = _commit_file(worktree.path, "work.txt", "first phase")
    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)

    import app.routes.sessions as sessions_route

    merged = await sessions_route.execute_merge_session(
        session_id=found.id,
        expected_name=found.name,
        expected_scope=found.scope,
        expected_branch=found.branch,
        expected_head=head,
        req={"scope": scope, "merge_schema_version": 2, "task_outcome": "continue"},
    )
    assert merged["ok"] is True, merged
    assert _rev(worktree.path) == _rev(repo, "main")
    assert _runs(name)[current_ref]["status"] == "requested"
    return repo, worktree, current, following


async def _switch(name: str, repo, task_ref: str, **extra):
    import app.routes.sessions as sessions_route

    return await sessions_route.switch_branch(
        name, {"scope": str(repo), "task_id": task_ref, **extra},
    )


def _assert_still_bound(name, current, following):
    from app import tm
    from app.db import get_session

    current_ref = tm.public_task_ref(current)
    kept = _task(current["id"])
    assert (kept["status"], kept["worker_session_id"]) == ("in_progress", name)
    assert _runs(name)[current_ref]["status"] == "requested"
    queued = _task(following["id"])
    assert (queued["status"], queued["worker_session_id"]) == ("new", None)
    assert get_session(name)["task_id"] == current_ref


@pytest.mark.asyncio
async def test_switch_releases_clean_worker_and_requeues_previous_task(monkeypatch, tmp_path):
    from app import tm
    from app.db import get_session

    name = "release-worker"
    repo, worktree, current, following = await _worker_after_continue(
        monkeypatch, tmp_path, name,
    )
    current_ref, next_ref = tm.public_task_ref(current), tm.public_task_ref(following)

    result = await _switch(name, repo, next_ref)

    assert result.get("ok") is True, result
    released = _task(current["id"])
    assert (released["status"], released["worker_session_id"]) == ("new", None)
    runs = _runs(name)
    assert (runs[current_ref]["status"], runs[current_ref]["failure_code"]) == (
        "interrupted", "binding_released",
    )
    assert runs[next_ref]["status"] == "requested"
    assigned = _task(following["id"])
    assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)
    lifecycle = get_session(name)
    assert (lifecycle["task_id"], lifecycle["branch"]) == (next_ref, f"task-{next_ref}/{name}")
    assert result["task_status"]["previous_tasks"] == [
        {"task": current_ref, "outcome": "released"},
    ]


@pytest.mark.asyncio
async def test_switch_with_complete_previous_closes_task_as_done_with_note(
    monkeypatch, tmp_path,
):
    from app import tm

    name = "done-worker"
    repo, worktree, current, following = await _worker_after_continue(
        monkeypatch, tmp_path, name,
    )
    current_ref, next_ref = tm.public_task_ref(current), tm.public_task_ref(following)
    head = _rev(worktree.path)

    missing_note = await _switch(name, repo, next_ref, complete_previous=True)
    assert missing_note.status_code == 400
    _assert_still_bound(name, current, following)

    result = await _switch(
        name, repo, next_ref,
        complete_previous=True, acceptance_note="phase merged in continue; verified on main",
    )

    assert result.get("ok") is True, result
    closed = _task(current["id"])
    assert (closed["status"], closed["worker_session_id"]) == ("done", None)
    run = _runs(name)[current_ref]
    assert run["status"] == "completed"
    assert run["verdict_value"] == "phase merged in continue; verified on main"
    assert run["worker_head"] == head
    assigned = _task(following["id"])
    assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)


@pytest.mark.asyncio
@pytest.mark.parametrize("held", ["uncommitted", "unmerged_commit"])
@pytest.mark.parametrize("mode", ["plain", "force", "complete_previous"])
async def test_switch_keeps_binding_while_worker_holds_unlanded_work(
    monkeypatch, tmp_path, held, mode,
):
    from app import tm

    name = "holding-worker"
    repo, worktree, current, following = await _worker_after_continue(
        monkeypatch, tmp_path, name,
    )
    if held == "uncommitted":
        (Path(worktree.path) / "pending.txt").write_text("pending")
    else:
        _commit_file(worktree.path, "later.txt", "second phase")
    extra = {
        "plain": {},
        "force": {"force": True},
        "complete_previous": {"complete_previous": True, "acceptance_note": "claimed done"},
    }[mode]

    result = await _switch(name, repo, tm.public_task_ref(following), **extra)

    if mode == "complete_previous":
        assert result.status_code == 409
    else:
        assert result.get("ok") is not True, result
    _assert_still_bound(name, current, following)
