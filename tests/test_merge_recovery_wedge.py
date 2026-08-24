"""Oracles for the two #248 T3 review blockers: restart recovery and reservation release.

Both describe the same shape of loss — Git already moved `main`, but the platform never
finishes the thought, and the task is left permanently unassignable:

1. A restart between the Git commit and the first checkpoint leaves `UNKNOWN` forever:
   `recover_orphan_operations` marks the row and never asks the repository whether our
   own commit is sitting in `main` under our own trailer.
2. `resolve_merge_operation` — advertised as "the ONLY way to unblock merges" — does not
   release the reservation, so the operator following that instruction wedges the task.

Each test carries a PERMITTING control arm: a recovery that accepts everything, or a
release that drops every reservation, is not a fix and must not pass.
"""

import asyncio
import json
import subprocess
import uuid

import pytest

from tests.test_task_tracker_integration import (
    _commit_file,
    _init_db,
    _make_git_scope,
    _prepare_merge,
    _save_worker,
)


def _crash_after_git(operation_id: str) -> None:
    """Rewrite the row into the state a crash between Git and the checkpoint leaves.

    `save_prepared_finalization` runs BEFORE Git, so the payload survives; what a crash
    destroys is the first post-Git write. That is exactly RUNNING + PREPARED.
    """
    import app.merge_operations as operations

    with operations._conn() as connection:
        connection.execute(
            "UPDATE merge_operations "
            "SET state='RUNNING', commit_point='UNKNOWN', finalization_stage='PREPARED', "
            "    finished_at='', owner_token='' "
            "WHERE operation_id=?",
            (operation_id,),
        )


async def _merge_then_rewind_to_crash(monkeypatch, tmp_path, *, worker: str):
    """Perform a real merge, then rewind the DB to the state a crash would leave.

    Rewinding beats injecting a fault: the injection point is inside the very recovery
    path under test, so a raise there proves nothing about a process that simply died.
    Everything Git did stays; every post-Git DB effect is undone.
    """
    import app.merge_operations as operations
    import app.routes.merge_operations as merge_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = tm.create_task(
            connection, "project", "Wedge me", par_number=42, status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?", (worker, task["id"]),
        )
    worktree = workspace.create_worktree(scope, worker, task_id="42")
    _commit_file(worktree.path, "wedge.txt", "#42: wedge recovery")
    _save_worker(
        session_id=worker, task_id="42", scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    found = _prepare_merge(monkeypatch, session_id=worker, scope=scope)
    target_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    merge_calls = {"n": 0}
    real_merge = workspace.merge_worktree_to_main

    def counted(*args, **kwargs):
        merge_calls["n"] += 1
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(workspace, "merge_worktree_to_main", counted)
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
    assert operations.get_operation_record(operation_id)["state"] == "SUCCEEDED"

    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET status='in_progress', worker_session_id=?, "
            "completed_at=NULL, git_commits='[]' WHERE id=?",
            (worker, task["id"]),
        )
        connection.execute(
            "INSERT INTO tm_task_reservations "
            "(task_id, operation_id, kind, session_id, created_at) VALUES (?,?,?,?,?)",
            (task["id"], operation_id, "complete", worker, "2026-08-13T00:00:00Z"),
        )

    return {
        "operation_id": operation_id,
        "repo": repo,
        "task_id": task["id"],
        "target_before": target_before,
        "merge_calls": merge_calls,
    }


@pytest.mark.asyncio
async def test_restart_after_git_recovers_the_commit_instead_of_wedging(
    monkeypatch, tmp_path,
):
    """A crash between Git and the checkpoint must not leave the task open forever."""
    import app.merge_operations as operations
    from app import tm

    state = await _merge_then_rewind_to_crash(
        monkeypatch, tmp_path, worker="restart-worker",
    )
    repo = state["repo"]
    head_after_git = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert head_after_git != state["target_before"], "the merge must have reached Git"
    _crash_after_git(state["operation_id"])

    # The server comes back up.
    await operations.restore_merge_operations()
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))

    record = operations.get_operation_record(state["operation_id"])
    assert record["state"] != "UNKNOWN", (
        "our own commit is in main under our own trailer: recovery must read the "
        "repository, not give up"
    )
    with tm._conn() as connection:
        closed = tm.get_task_by_id(connection, state["task_id"])
    assert closed["status"] == "done"
    assert state["merge_calls"]["n"] == 1, "recovery must never re-run Git"
    assert subprocess.run(
        ["git", "rev-list", "--count", f"{state['target_before']}..main"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "1"
    with tm._conn() as connection:
        held = connection.execute(
            "SELECT 1 FROM tm_task_reservations WHERE task_id=?", (state["task_id"],),
        ).fetchone()
    assert held is None, "a finished operation must not keep the task reserved"


@pytest.mark.asyncio
async def test_restart_does_not_claim_a_commit_that_is_not_ours(monkeypatch, tmp_path):
    """Control arm: recovery that accepts anything is not recovery."""
    import app.merge_operations as operations

    state = await _merge_then_rewind_to_crash(
        monkeypatch, tmp_path, worker="foreign-worker",
    )
    repo = state["repo"]
    # Someone else's history sits where our commit used to be.
    subprocess.run(
        ["git", "reset", "--hard", state["target_before"]], cwd=repo,
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "#42: unrelated foreign work"],
        cwd=repo, check=True, capture_output=True,
    )
    _crash_after_git(state["operation_id"])

    await operations.restore_merge_operations()
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))

    record = operations.get_operation_record(state["operation_id"])
    assert record["state"] == "UNKNOWN", (
        "without our trailer the outcome is genuinely unknown and must stay so"
    )


@pytest.mark.asyncio
async def test_resolving_an_unknown_operation_frees_its_task(monkeypatch, tmp_path):
    """The documented unblock action must not leave the task permanently unassignable."""
    import app.merge_operations as operations
    import app.routes.merge_operations as merge_route
    from app import tm

    state = await _merge_then_rewind_to_crash(
        monkeypatch, tmp_path, worker="wedged-worker",
    )
    task_id = state["task_id"]
    _crash_after_git(state["operation_id"])
    # A restart that cannot reconcile: the repository no longer shows our commit.
    subprocess.run(
        ["git", "reset", "--hard", state["target_before"]], cwd=state["repo"],
        check=True, capture_output=True,
    )
    await operations.restore_merge_operations()
    if operations._runner_tasks:
        await asyncio.gather(*list(operations._runner_tasks.values()))
    assert operations.get_operation_record(state["operation_id"])["state"] == "UNKNOWN"

    # REFUSING ARM: while the operation is open the task is legitimately held.
    with tm._conn() as connection:
        assert connection.execute(
            "SELECT 1 FROM tm_task_reservations WHERE task_id=?", (task_id,),
        ).fetchone() is not None

    response = await merge_route.resolve_merge_operation(
        state["operation_id"],
        {"reason": "verified in main by hand", "actor": "orchestrator"},
    )
    # The resolved record legitimately keeps its original UNKNOWN error; what must
    # change is the block, so assert acceptance by status, not by an empty error.
    assert response.status_code == 200, json.loads(response.body)

    # PERMITTING ARM: after the operator resolves it, the task is workable again.
    with tm._conn() as connection:
        assert connection.execute(
            "SELECT 1 FROM tm_task_reservations WHERE task_id=?", (task_id,),
        ).fetchone() is None, (
            "resolve_merge_operation is documented as the only unblock path: "
            "leaving the reservation makes the task permanently unassignable"
        )
    _save_worker(
        session_id="next-worker",
        task_id="",
        scope=str(state["repo"]),
        worktree_path="/next-worker",
    )
    tm.bind_task_to_session(str(state["repo"]), "next-worker", "42")
    with tm._conn() as connection:
        rebound = tm.get_task_by_id(connection, task_id)
    assert rebound["worker_session_id"] == "next-worker"
