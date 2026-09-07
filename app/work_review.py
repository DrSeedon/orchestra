"""Advisory review for new work; execution history never authorizes a merge."""
from __future__ import annotations

import subprocess
from pathlib import Path

ASSIGNMENT_VERSION = 3
POLICY = "work-review-v2"
MAX_REVIEW_REQUESTS = 3


class ReviewBudgetError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def assignment(scope: str, session_id: str, task_id: str, *, connection=None) -> dict | None:
    if not session_id or not task_id:
        return None
    if connection is None:
        from app.db import _conn
        with _conn() as conn:
            return assignment(scope, session_id, task_id, connection=conn)
    row = connection.execute(
        "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
        "AND scope=? AND session_id=? AND task_id=? "
        "ORDER BY requested_at DESC, rowid DESC LIMIT 1",
        (scope.rstrip('/'), session_id, str(task_id)),
    ).fetchone()
    return dict(row) if row else None


def is_advisory(run: dict | None) -> bool:
    return bool(run and int(run.get("schema_version") or 1) >= ASSIGNMENT_VERSION)


def assignment_version(connection, scope: str, task_id: str, stable_id: str) -> int:
    # A replacement executor inherits the TASK's policy, not the time of its own spawn.
    identity = "(task_stable_id=? OR (task_stable_id='' AND task_id=?))" if stable_id else "task_id=?"
    args = (stable_id, task_id) if stable_id else (task_id,)
    row = connection.execute(
        "SELECT schema_version FROM review_receipts WHERE subject_kind='task_run' "
        f"AND scope=? AND {identity} ORDER BY requested_at, rowid LIMIT 1",
        (scope, *args),
    ).fetchone()
    return int(row[0]) if row else ASSIGNMENT_VERSION


def _task_reviews(connection, run: dict) -> list[dict]:
    stable_id = str(run.get("task_stable_id") or "")
    key = "task_stable_id" if stable_id else "task_id"
    value = stable_id or str(run["task_id"])
    return [dict(row) for row in connection.execute(
        f"SELECT * FROM review_receipts WHERE scope=? AND {key}=? "
        "AND mode IN ('implementation','exec','review') "
        "ORDER BY requested_at DESC, rowid DESC",
        (run["scope"], value),
    ).fetchall()]


def reserve_budget(connection, values: dict) -> None:
    """Called inside the receipt insert's BEGIN IMMEDIATE transaction."""
    run = assignment(str(values.get("scope") or ""), str(values.get("session_id") or ""),
                     str(values.get("task_id") or ""), connection=connection)
    if not is_advisory(run):
        return
    if run["status"] != "requested":
        raise ReviewBudgetError("review_task_not_active", "The task assignment is already closed; no new review can be requested.")
    rows = _task_reviews(connection, run)
    active = next((row for row in rows if row["status"] == "requested"), None)
    if active:
        raise ReviewBudgetError("review_in_progress", f"Review {active['receipt_id']} is still active; wait for its outcome.")
    if len(rows) >= MAX_REVIEW_REQUESTS:
        raise ReviewBudgetError("review_budget_exhausted", "Task review budget exhausted (3 attempts, including failures). Submit the evidence already available; do not rename the output or task to retry.")
    values.update(schema_version=ASSIGNMENT_VERSION, policy_ref=POLICY, scope=run["scope"],
                  task_stable_id=str(run.get("task_stable_id") or ""),
                  task_snapshot_ref=str(run.get("task_snapshot_ref") or ""))


def summarize_review(*, scope: str, session_id: str, task_id: str,
                     worktree: str, worker_head: str) -> dict:
    from app.db import _conn
    with _conn() as conn:
        run = assignment(scope, session_id, task_id, connection=conn)
        if not is_advisory(run):
            raise ValueError("assignment does not use advisory review")
        rows = _task_reviews(conn, run)
    reviews = [{
        "receipt_id": row["receipt_id"], "mode": row["mode"], "status": row["status"],
        "model": row["reviewer_model"], "reviewed_head": row["worker_head"],
        "artifact_path": row["artifact_path"],
        "artifact_available": Path(row["artifact_path"]).is_file() if row["artifact_path"] else False,
        "failure_code": row["failure_code"],
    } for row in rows]
    code_review = next((row for row in rows if row["mode"] == "implementation"
                        and row["status"] == "completed" and row["worker_head"]), None)
    delta = None
    comparison_error = ""
    if code_review:
        try:
            compared = subprocess.run(
                ["git", "diff", "--name-only", "-z", str(code_review["worker_head"]), worker_head, "--"],
                cwd=worktree, capture_output=True, text=True, timeout=15, check=False,
            )
            if compared.returncode == 0:
                delta = [p for p in compared.stdout.split('\0') if p]
            else:
                comparison_error = compared.stderr.strip() or "reviewed commit is unavailable"
        except (OSError, subprocess.TimeoutExpired) as error:
            comparison_error = f"review comparison unavailable: {type(error).__name__}"

    return {
        "policy": POLICY, "task_run_id": run["receipt_id"], "required": False, "status": "advisory", "worker_head": worker_head,
        "review_state": "recorded" if reviews else "not_requested", "reviews": reviews,
        "reviewed_head": str(code_review["worker_head"]) if code_review else "",
        "changed_after_review": delta, "comparison_error": comparison_error,
        "attempts_used": len(rows), "attempt_limit": MAX_REVIEW_REQUESTS,
    }
