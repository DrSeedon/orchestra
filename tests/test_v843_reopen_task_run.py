import subprocess

import pytest

from tests.task_seeds import create_task as seed_task
from tests.test_task_tracker_integration import (
    _commit_file,
    _init_db,
    _make_git_scope,
    _prepare_merge,
    _save_worker,
)


def _git(path, *args):
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _task_runs(session_id):
    from app import tm

    with tm._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM review_receipts WHERE subject_kind='task_run' AND session_id=?",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_v843_same_branch_switch_reopens_released_run_and_allows_merge(
    monkeypatch, tmp_path,
):
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    name = "reopen-worker"
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        task = seed_task(conn, "project", "Resume after partial", par_number=843)
    task_ref = tm.public_task_ref(task)
    worktree = workspace.create_worktree(scope, name, task_id=task_ref)
    _save_worker(
        session_id=name, task_id=task_ref, scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    tm.bind_task_to_session(scope, name, task_ref)
    head = _commit_file(worktree.path, "work.txt", "resume after binding release")

    # Same durable effect as PARTIAL finalization releasing the unfinished task.
    with tm.active_runtime().operation():
        with tm._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tm.release_session_task_binding(conn, name)
            conn.commit()
    rows = _task_runs(name)
    assert [(row["status"], row["failure_code"]) for row in rows] == [
        ("interrupted", "binding_released"),
    ]

    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)
    resumed = await sessions_route.switch_branch(
        name, {"scope": scope, "task_id": task_ref},
    )
    assert resumed["ok"] is True, resumed
    assert resumed["state"] == "task_run_reopened"
    with tm._conn() as conn:
        current_task = tm.get_task_by_id(conn, task["id"])
    assert (current_task["status"], current_task["worker_session_id"]) == (
        "in_progress", name,
    )
    rows = _task_runs(name)
    assert [row["status"] for row in rows] == ["interrupted", "requested"]

    monkeypatch.setattr(
        "app.workspace.classify_head_drift",
        lambda _path, branch, expected: {
            "class": "SAME", "actual_branch": branch, "actual_head": expected,
            "reason": "",
        },
    )
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "merged_commits": {
                task_ref: [{"hash": "v843abc", "message": "#843: resumed"}],
            },
        },
    )
    merged = await sessions_route.execute_merge_session(
        session_id=name,
        expected_name=name,
        expected_scope=scope,
        expected_branch=worktree.branch,
        expected_head=head,
        req={"scope": scope, "task_outcome": "complete", "merge_schema_version": 2},
    )
    assert merged["ok"] is True, merged


@pytest.mark.asyncio
async def test_v843_stale_worker_head_still_refuses_merge(monkeypatch, tmp_path):
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    name = "stale-head-worker"
    with tm._conn() as conn:
        tm.ensure_project(conn, "project", scope=scope)
        task = seed_task(
            conn, "project", "Reject stale snapshot", par_number=844,
            status="in_progress",
        )
        conn.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?", (name, task["id"]),
        )
    task_ref = tm.public_task_ref(task)
    worktree = workspace.create_worktree(scope, name, task_id=task_ref)
    _save_worker(
        session_id=name, task_id=task_ref, scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    tm.bind_task_to_session(scope, name, task_ref)
    stale_head = _git(worktree.path, "rev-parse", "HEAD")
    _commit_file(worktree.path, "later.txt", "head moved")
    from app.workspace import classify_head_drift

    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)
    monkeypatch.setattr("app.workspace.classify_head_drift", classify_head_drift)
    merge_calls = []

    def unexpected_merge(*_args, **_kwargs):
        merge_calls.append("merge")
        return {"ok": True, "commits_merged": 1, "merged_commits": {}}

    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        unexpected_merge,
    )

    result = await sessions_route.execute_merge_session(
        session_id=name,
        expected_name=name,
        expected_scope=scope,
        expected_branch=worktree.branch,
        expected_head=stale_head,
        req={
            "scope": scope, "task_outcome": "complete", "merge_schema_version": 2,
            "expected_head": stale_head,
        },
    )
    assert result["ok"] is False
    assert "HEAD changed" in result["error"]
    assert merge_calls == []
