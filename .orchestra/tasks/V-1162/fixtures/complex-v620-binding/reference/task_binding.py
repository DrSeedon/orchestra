from __future__ import annotations

import sqlite3
import subprocess
import uuid


def _git(repo: str, *args: str) -> str:
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def _open(db_path: str):
    connection = sqlite3.connect(db_path, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _worktree_is_clean(repo: str) -> bool:
    return not _git(repo, "status", "--porcelain", "--untracked-files=all")


def _commits_ahead(repo: str, target_branch: str) -> int:
    return int(_git(repo, "rev-list", "--count", f"{target_branch}..HEAD"))


def switch_worker(
    db_path: str,
    repo_path: str,
    worker: str,
    next_task: str,
    *,
    target_branch: str = "main",
    complete_previous: bool = False,
    note: str = "",
) -> str:
    if complete_previous and not note.strip():
        raise ValueError("completion note is required")
    if not _worktree_is_clean(repo_path) or _commits_ahead(repo_path, target_branch):
        raise RuntimeError("unlanded work prevents switching tasks")

    connection = _open(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        binding = connection.execute(
            "SELECT task_id, run_id FROM bindings WHERE worker=?", (worker,)
        ).fetchone()
        new_task = connection.execute(
            "SELECT status FROM tasks WHERE task_id=?", (next_task,)
        ).fetchone()
        if not new_task or new_task["status"] != "new":
            raise RuntimeError("next task is not available")
        new_run = str(uuid.uuid4())

        if binding:
            other_bindings = connection.execute(
                "SELECT COUNT(*) FROM bindings WHERE task_id=? AND worker<>?",
                (binding["task_id"], worker),
            ).fetchone()[0]
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id=?", (binding["run_id"],)
            ).fetchone()
            if not run or run["status"] != "requested":
                raise RuntimeError("current task run is not open")
            if complete_previous:
                if other_bindings:
                    raise RuntimeError("another worker still owns the previous task")
                connection.execute(
                    "UPDATE tasks SET status='done' WHERE task_id=?",
                    (binding["task_id"],),
                )
                connection.execute(
                    "UPDATE runs SET status='completed', note=?, head=? WHERE run_id=?",
                    (note.strip(), _git(repo_path, "rev-parse", "HEAD"), binding["run_id"]),
                )
            else:
                if not other_bindings:
                    connection.execute(
                        "UPDATE tasks SET status='new' WHERE task_id=?",
                        (binding["task_id"],),
                    )
                connection.execute(
                    "UPDATE runs SET status='interrupted', reason='binding_released', head=? WHERE run_id=?",
                    (_git(repo_path, "rev-parse", "HEAD"), binding["run_id"]),
                )
            connection.execute("DELETE FROM bindings WHERE worker=?", (worker,))

        connection.execute(
            "UPDATE tasks SET status='in_progress' WHERE task_id=?",
            (next_task,),
        )
        connection.execute(
            "INSERT INTO runs(run_id, task_id, worker, status) VALUES (?, ?, ?, 'requested')",
            (new_run, next_task, worker),
        )
        connection.execute(
            "INSERT INTO bindings(worker, task_id, run_id) VALUES (?, ?, ?)",
            (worker, next_task, new_run),
        )
        connection.commit()
        return new_run
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_committed_work(db_path: str, repo_path: str, worker: str, target_branch: str = "main") -> str:
    branch = _git(repo_path, "branch", "--show-current")
    commit = _git(repo_path, "rev-parse", "HEAD")
    if branch == target_branch:
        raise RuntimeError("worker branch must be distinct from target")
    _git(repo_path, "checkout", target_branch)
    _git(repo_path, "merge", "--ff-only", branch)
    _git(repo_path, "checkout", branch)
    connection = _open(db_path)
    try:
        with connection:
            binding = connection.execute(
                "SELECT task_id, run_id FROM bindings WHERE worker=?", (worker,)
            ).fetchone()
            if not binding:
                raise RuntimeError("worker has no task binding")
            connection.execute(
                "UPDATE tasks SET status='done' WHERE task_id=?",
                (binding["task_id"],),
            )
            connection.execute(
                "UPDATE runs SET status='completed', head=? WHERE run_id=?",
                (commit, binding["run_id"]),
            )
            connection.execute("DELETE FROM bindings WHERE worker=?", (worker,))
        return commit
    finally:
        connection.close()
