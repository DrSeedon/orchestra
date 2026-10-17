# Candidate cand-57

## ORIGIN commit 0f973de21a (2026-09-23): V-620: switch_worker_branch releases a worker left bound after merge(continue)
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/db.py b/app/db.py
index d64fdfc2f..400a8a29a 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1468,19 +1468,25 @@ def task_run_receipt_open(
 def task_run_receipt_finish(
     *,
     session_id: str,
     task_id: str,
     status: str,
     prompt_template_end: str,
     terminal_operation_id: str = "",
     failure_code: str = "",
+    acceptance_note: str = "",
+    worker_head: str = "",
     connection: sqlite3.Connection | None = None,
 ) -> dict:
-    """Finish the single open task run; identical terminal replay is safe."""
+    """Finish the single open task run; identical terminal replay is safe.
+
+    `acceptance_note`/`worker_head` record why and at which HEAD an orchestrator declared
+    the run done outside a merge; they land in the run's verdict columns.
+    """
     if status not in {"completed", "interrupted"}:
         raise ValueError("task run terminal status must be completed or interrupted")
     terminal_operation_id = str(terminal_operation_id or "")
     prompt_template_end = str(prompt_template_end or "")
     failure_code = str(failure_code or "")
     owner = nullcontext(connection) if connection is not None else _conn()
     with owner as c:
         if connection is None:
@@ -1522,24 +1528,28 @@ def task_run_receipt_finish(
                 and str(saved["terminal_operation_id"] or "") == terminal_operation_id
                 and str(saved["failure_code"] or "") == failure_code
             ):
                 return saved
             raise ValueError("task run already has a different terminal outcome")
         receipt_id = rows[0]["receipt_id"]
         c.execute(
             "UPDATE review_receipts SET status=?,completed_at=?,failure_code=?,"
-            "prompt_template_end=?,terminal_operation_id=? "
+            "prompt_template_end=?,terminal_operation_id=?,"
+            "verdict_present=?,verdict_value=?,worker_head=? "
             "WHERE receipt_id=? AND status='requested'",
             (
                 status,
                 datetime.now(timezone.utc).isoformat(),
                 failure_code,
                 prompt_template_end,
                 terminal_operation_id,
+                1 if acceptance_note else None,
+                str(acceptance_note or ""),
+                str(worker_head or ""),
                 receipt_id,
             ),
         )
         return dict(c.execute(
             "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,),
         ).fetchone())
 
 
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 6161f255f..ec834d8bf 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2624,31 +2624,39 @@ async def resolve_merge_operation(operation_id: str, reason: str) -> CallToolRes
 @mcp.tool()
 async def switch_worker_branch(
     name: str,
     task_id: str,
     from_ref: str = "",
     force: bool = False,
     promote_current: bool = False,
     owned_dirs: str = "",
+    complete_previous: bool = False,
+    acceptance_note: str = "",
 ) -> str:
     """After merge, switch worker to a new branch for a new task.
     from_ref — optional local base override; empty uses the worker's persisted base.
     force=True explicitly discards committed content not verified in the base.
     promote_current=True preserves and assigns committed taskless adhoc work.
     owned_dirs — optional JSON array replacing the worker's ownership on a new task;
     omitted or [] clears it.
+    A clean worker with nothing unmerged is released from its previous task, which
+    returns to the queue; complete_previous=True closes it as done instead and requires
+    acceptance_note (why it is done).
     Worker must be idle with clean working tree."""
     payload = {
         "scope": SCOPE,
         "task_id": task_id,
         "from_ref": from_ref,
         "force": force,
         "promote_current": promote_current,
     }
+    if complete_previous or acceptance_note:
+        payload["complete_previous"] = complete_previous
+        payload["acceptance_note"] = acceptance_note
     if owned_dirs:
         try:
             parsed_owned_dirs = json.loads(owned_dirs)
         except (TypeError, ValueError) as error:
             return f"Switch failed: owned_dirs is not valid JSON: {error}"
         if not isinstance(parsed_owned_dirs, list):
             return "Switch failed: owned_dirs must be a JSON array"
         payload["owned_dirs"] = parsed_owned_dirs
@@ -2672,17 +2680,23 @@ async def switch_worker_branch(
         isinstance(result, dict)
         and result.get("ok")
         and result.get("state") == "already_current"
     ):
         return (
             f"No-op: worker is already on healthy branch {result.get('branch', '?')}"
         )
     if isinstance(result, dict) and result.get("ok"):
-        return f"Switched to branch {result.get('branch', '?')}"
+        task_status = result.get("task_status") if isinstance(result.get("task_status"), dict) else {}
+        previous = "; ".join(
+            f"previous task {item.get('task')} {item.get('outcome')}"
+            for item in task_status.get("previous_tasks") or []
+            if isinstance(item, dict)
+        )
+        return f"Switched to branch {result.get('branch', '?')}" + (f"; {previous}" if previous else "")
     if isinstance(result, dict) and result.get("conflicts"):
         return f"Merge conflict with base branch on: {', '.join(result['conflicts'])}"
     return f"Switch result: {result}"
 
 
 @mcp.tool()
 async def check_conflict(worker_a: str, worker_b: str) -> str:
     """Dry-run: would merging these two workers' branches conflict? Both must have committed work.
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 55941b3d5..3d16eafa2 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -164,16 +164,36 @@ def _session_base_branch(session, requested: str = "") -> str:
     from app.workspace import resolve_base_branch
 
     worktree_path = session.worktree_path
     if not worktree_path:
         raise ValueError("session has no worktree")
     return resolve_base_branch(worktree_path, requested or getattr(session, "base_branch", ""))
 
 
+def _unlanded_work(session, worktree_path: str) -> dict:
+    """Describe worker work that has not reached its base; an empty reason means none."""
+    from app.workspace import branch_wip_status, inspect_worktree_identity
+
+    try:
+        base = _session_base_branch(session, "")
+        wip = branch_wip_status(worktree_path, base_ref=base)
+        _branch, head = inspect_worktree_identity(worktree_path)
+    except Exception as error:
+        return {"reason": f"worker branch state is unknown: {err_text(error)}", "head": ""}
+    if wip.get("error"):
+        return {"reason": f"worker branch state is unknown: {wip['error']}", "head": head}
+    parts = []
+    if wip["uncommitted"]:
+        parts.append(f"{len(wip['uncommitted'])} uncommitted file(s)")
+    if wip["unmerged_commits"]:
+        parts.append(f"{len(wip['unmerged_commits'])} commit(s) not in {base}")
+    return {"reason": ", ".join(parts), "head": head}
+
+
 class CreateSessionRequest(BaseModel):
     name: str
     cwd: str
     model: str = "claude-sonnet-5[1m]"
     scope: Optional[str] = None
     system_prompt: str = ""
     use_worktree: bool = False
     repo_path: Optional[str] = None
@@ -2885,26 +2905,43 @@ async def _promote_current_work_for_task(
 @router.post("/api/sessions/{name}/switch-branch")
 async def switch_branch(name: str, req: dict):
     from app.workspace import inspect_worktree_identity, switch_worktree_branch
     from app import tm as _tm
     scope = req.get("scope", "")
     task_id = req.get("task_id", "")
     force = req.get("force", False)
     promote_current = req.get("promote_current", False)
+    complete_previous = req.get("complete_previous", False)
+    acceptance_note = req.get("acceptance_note", "")
     if not task_id:
         return JSONResponse({"error": "task_id required"}, status_code=400)
     if not isinstance(force, bool):
         return JSONResponse({"error": "force must be a boolean"}, status_code=400)
     if not isinstance(promote_current, bool):
         return JSONResponse({"error": "promote_current must be a boolean"}, status_code=400)
+    if not isinstance(complete_previous, bool):
+        return JSONResponse({"error": "complete_previous must be a boolean"}, status_code=400)
+    if not isinstance(acceptance_note, str):
+        return JSONResponse({"error": "acceptance_note must be a string"}, status_code=400)
+    acceptance_note = acceptance_note.strip()
     if promote_current and force:
         return JSONResponse(
             {"error": "promote_current cannot be combined with force"}, status_code=400,
         )
+    if complete_previous and (promote_current or force):
+        return JSONResponse(
+            {"error": "complete_previous cannot be combined with promote_current or force"},
+            status_code=400,
+        )
+    if complete_previous and not acceptance_note:
+        return JSONResponse(
+            {"error": "complete_previous requires an acceptance_note: why the previous task is done"},
+            status_code=400,
+        )
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     scope = (getattr(found, "scope", "") or scope).rstrip("/")
     try:
         task_identity = await asyncio.to_thread(
             _tm.resolve_scoped_task_identity, scope, task_id,
         )
@@ -2929,16 +2966,21 @@ async def switch_branch(name: str, req: dict):
     session_id = found.id
     previous_branch = getattr(found, "branch", "") or ""
     previous_base_branch = getattr(found, "base_branch", "") or ""
     previous_task_id = str(getattr(found, "task_id", "") or "")
     previous_needs_switch = bool(getattr(found, "needs_switch", False))
     previous_owned_dirs = list(getattr(found, "owned_dirs", []) or [])
     if not worktree_path:
         return JSONResponse({"error": "session has no worktree"}, status_code=400)
+    if complete_previous and not (new_task and previous_task_id):
+        return JSONResponse(
+            {"error": "complete_previous needs a bound previous task and a different task_id"},
+            status_code=400,
+        )
     new_branch = f"task-{par}/{name}"
     try:
         from_ref = _session_base_branch(found, req.get("from_ref", ""))
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=400)
     from app.manager import LockBusy, wait_for_session_lock
 
     try:
@@ -3039,16 +3081,43 @@ async def switch_branch(name: str, req: dict):
                     return {
                         "ok": True,
                         "state": "lifecycle_repaired",
                         "branch": previous_branch,
                         "task_status": binding,
                         "waited_seconds": round(waited_seconds, 2),
                         "message": "task/branch binding repaired",
                     }
+                # Прежняя задача держит воркера открытым прогоном, пока её не закроет мерж, —
+                # после merge(continue) закрывать уже нечем (V-620). Отпустить её можно, только
+                # пока снимок ДО git показывает, что работы на ветке нет; сам выпуск идёт в
+                # транзакции назначения новой задачи и откатывается вместе с ней.
+                release_previous = None
+                held_work = {"reason": "", "head": ""}
+                if new_task and previous_task_id:
+                    held_work = await asyncio.to_thread(
+                        _unlanded_work, found, worktree_path,
+                    )
+                    if not held_work["reason"]:
+                        release_previous = {
+                            "session_id": session_id,
+                            "done_note": acceptance_note if complete_previous else "",
+                            "worker_head": held_work["head"],
+                        }
+                    elif complete_previous:
+                        return JSONResponse(
+                            {
+                                "error": (
+                                    f"cannot close task {previous_task_id} as done: "
+                                    f"{held_work['reason']}; merge or discard that work first"
+                                ),
+                                "waited_seconds": round(waited_seconds, 2),
+                            },
+                            status_code=409,
+                        )
                 try:
                     verdict = await asyncio.to_thread(
                         _existing_branch_verdict, worktree_path, new_branch,
                         found.scope or scope, force,
                     )
                     if verdict.get("error"):
                         return JSONResponse(
                             {**verdict, "waited_seconds": round(waited_seconds, 2)},
@@ -3100,20 +3169,30 @@ async def switch_branch(name: str, req: dict):
                             }
                             return result
                         task_assignment_raised = False
                         try:
                             result["task_status"] = await asyncio.to_thread(
                                 _tm.api_update_task_if_current,
                                 task_identity,
                                 status="in_progress",
+                                release_previous=release_previous,
                             )
                         except Exception as task_error:
                             task_assignment_raised = True
                             detail = err_text(task_error)
+                            if (
+                                release_previous is None
+                                and previous_task_id
+                                and "open task run" in detail
+                            ):
+                                detail += (
+                                    f"; worker still holds task {previous_task_id}: "
+                                    f"{held_work['reason']} — merge or discard that work first"
+                                )
                             result["task_status"] = {"ok": False, "error": detail}
                         if not result["task_status"].get("ok"):
                             if task_assignment_raised and previous_branch:
                                 try:
                                     rollback = await asyncio.to_thread(
                                         switch_worktree_branch,
                                         worktree_path,
                                         previous_branch,
diff --git a/app/tm.py b/app/tm.py
index ed29075d1..be5c30e79 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -818,16 +818,18 @@ def _open_task_run_for_task(
 def _finish_task_run_for_task(
     conn: sqlite3.Connection,
     task: dict,
     session_id: str,
     *,
     status: str,
     failure_code: str = "",
     terminal_operation_id: str = "",
+    acceptance_note: str = "",
+    worker_head: str = "",
 ) -> dict | None:
     exists = conn.execute(
         "SELECT 1 FROM review_receipts WHERE subject_kind='task_run' "
         "AND session_id=? AND task_id=? AND status='requested'",
         (session_id, public_task_ref(task)),
     ).fetchone()
     if exists is None:
         return None
@@ -836,16 +838,18 @@ def _finish_task_run_for_task(
     ).fetchone()
     return task_run_receipt_finish(
         session_id=session_id,
         task_id=public_task_ref(task),
         status=status,
         prompt_template_end=str(session["template_hash"] or "") if session else "",
         terminal_operation_id=terminal_operation_id,
         failure_code=failure_code,
+        acceptance_note=acceptance_note,
+        worker_head=worker_head,
         connection=conn,
     )
 
 
 def prepare_merge_finalization(
     *,
     scope: str,
     session_id: str,
@@ -1051,27 +1055,31 @@ def finalize_merge_outcome(payload: dict) -> dict:
                 )
             conn.commit()
         except Exception:
             conn.rollback()
             raise
     return {"ok": True, "links": links}
 
 
-def release_session_task_binding(conn: sqlite3.Connection, session_id: str) -> None:
+def release_session_task_binding(
+    conn: sqlite3.Connection, session_id: str, keep_task_id: int | None = None,
+) -> None:
     """Recompute every binding an archived session held: elect an heir or requeue.
 
     Liveness of a worker is a platform fact, so the last worker leaving an unfinished
     task returns it to the queue. Any other live worker on the same task keeps it
     `in_progress` — blind requeueing would abandon work that is still running.
+    `keep_task_id` spares the task the session is being moved onto.
     """
     rows = conn.execute(
         "SELECT t.*, p.scope FROM tm_tasks t "
-        "JOIN tm_projects p ON p.id = t.project_id WHERE t.worker_session_id = ?",
-        (session_id,),
+        "JOIN tm_projects p ON p.id = t.project_id "
+        "WHERE t.worker_session_id = ? AND t.id IS NOT ?",
+        (session_id, keep_task_id),
     ).fetchall()
     now = _now()
     session = conn.execute(
         "SELECT status FROM sessions WHERE id=?", (session_id,),
     ).fetchone()
     release_code = (
         "session_archived"
         if session and session["status"] == "archived"
@@ -1511,25 +1519,82 @@ def validate_task_binding_repair(
             )
         if task["status"] != "in_progress":
             raise ValueError(
                 f"task #{task['par_number']} is {task['status']}, not in_progress"
             )
         return task_dto(task)
 
 
+def _release_previous_binding(
+    conn: sqlite3.Connection,
+    *,
+    session_id: str,
+    keep_task_id: int,
+    done_note: str = "",
+    worker_head: str = "",
+) -> list[dict]:
+    """Free the tasks a switching session still holds, inside the caller's transaction.
+
+    Without `done_note` the session simply leaves: the platform release rule requeues the
+    task or hands it to another live worker. With it the orchestrator declares the task
+    done; that is refused while the task is reserved by a merge or held by another worker.
+    """
+    rows = [dict(row) for row in conn.execute(
+        "SELECT t.*, p.scope FROM tm_tasks t JOIN tm_projects p ON p.id = t.project_id "
+        "WHERE t.worker_session_id = ? AND t.id != ?",
+        (session_id, keep_task_id),
+    ).fetchall()]
+    for row in rows:
+        reserved = conn.execute(
+            "SELECT operation_id FROM tm_task_reservations WHERE task_id=?", (row["id"],),
+        ).fetchone()
+        if reserved:
+            raise ValueError(
+                f"task {public_task_ref(row)} is reserved by operation "
+                f"{reserved['operation_id']}; its binding is kept"
+            )
+    if not done_note:
+        release_session_task_binding(conn, session_id, keep_task_id=keep_task_id)
+        return [{"task": public_task_ref(row), "outcome": "released"} for row in rows]
+    for row in rows:
+        others = _live_bindings(conn, row["scope"], public_task_ref(row), session_id)
+        if others:
+            raise ValueError(
+                f"task {public_task_ref(row)} still has live workers "
+                f"({', '.join(sorted(others))}) — done is refused"
+            )
+        _finish_task_run_for_task(
+            conn, row, session_id, status="completed",
+            acceptance_note=done_note, worker_head=worker_head,
+        )
+        update_task(conn, row["id"], status="done")
+        conn.execute(
+            "UPDATE tm_tasks SET worker_session_id=NULL, "
+            "sync_revision=sync_revision+1, updated_at=? WHERE id=?",
+            (_now(), row["id"]),
+        )
+        active_runtime().publish(conn, row["id"])
+    return [{"task": public_task_ref(row), "outcome": "done"} for row in rows]
+
+
 def api_update_task_if_current(
     identity: TaskIdentity,
     *,
     status: str,
     worker_session_id: str | None = None,
     expected_status: str = "",
     require_unreserved: bool = False,
+    release_previous: dict | None = None,
 ) -> dict:
-    """Update a prevalidated task only while its immutable identity/version matches."""
+    """Update a prevalidated task only while its immutable identity/version matches.
+
+    `release_previous` ({session_id, done_note, worker_head}) frees the session's earlier
+    task in the same transaction, so a failed assignment keeps the old binding intact.
+    """
     with active_runtime().operation():
         if status not in VALID_STATUSES:
             raise ValueError(f"Invalid status: {status}")
         binding_inferred = worker_session_id is None and status == "in_progress"
         worker_session_id = _infer_task_worker_session(
             identity, status=status, worker_session_id=worker_session_id,
         )
         task_id = identity["id"]
@@ -1573,16 +1638,20 @@ def api_update_task_if_current(
                     expected_status=expected_status,
                     require_unreserved=require_unreserved,
                 )
                 if claim_error:
                     conn.rollback()
                     return {"ok": False, "task_id": task_id, "error": claim_error}
                 if binding_inferred and worker_session_id:
                     _validate_inferred_task_worker(conn, task, worker_session_id)
+                previous = (
+                    _release_previous_binding(conn, keep_task_id=task_id, **release_previous)
+                    if release_previous else []
+                )
                 result = update_task(
                     conn,
                     task_id,
                     status=status,
                     worker_session_id=worker_session_id,
                 )
                 active_runtime().publish(conn, task_id)
                 updated = get_task_by_id(conn, task_id)
@@ -1603,16 +1672,17 @@ def api_update_task_if_current(
 
         return {
             "ok": True,
             "task_id": task_id,
             "par": public_task_ref(identity),
             "updated": result["changed"],
             "new_status": updated["status"],
             "sync_revision": updated["sync_revision"],
+            **({"previous_tasks": previous} if previous else {}),
         }
 
 
 def api_list_tasks(project: str = "", status: str = "",
                    assignee: str = "", tags: list[str] | None = None) -> dict:
     with active_runtime().operation():
         with _conn() as conn:
             resolved_project, wanted_tags = "", list(tags or [])
diff --git a/tests/test_switch_after_continue_620.py b/tests/test_switch_after_continue_620.py
new file mode 100644
index 000000000..c02a85348
--- /dev/null
+++ b/tests/test_switch_after_continue_620.py
@@ -0,0 +1,198 @@
+"""V-620: a worker left on its task by merge(continue) must be switchable to a new task.
+
+merge(continue) resets the worker branch onto the target and keeps the task run open.
+With nothing left to merge, merge(complete) is refused, and switch_worker_branch used to
+fail on the still-open run — the worker stayed bound forever. The switch now frees the
+previous task when the worker has no unlanded work.
+"""
+
+import subprocess
+from pathlib import Path
+
+import pytest
+
+from tests.task_seeds import create_task as seed_task
+from tests.test_task_tracker_integration import (
+    _commit_file,
+    _init_db,
+    _make_git_scope,
+    _prepare_merge,
+    _save_worker,
+)
+
+
+def _rev(cwd, ref: str = "HEAD") -> str:
+    return subprocess.run(
+        ["git", "rev-parse", ref], cwd=cwd, check=True, capture_output=True, text=True,
+    ).stdout.strip()
+
+
+def _runs(session_id: str) -> dict[str, dict]:
+    from app import tm
+
+    with tm._conn() as connection:
+        rows = connection.execute(
+            "SELECT * FROM review_receipts WHERE subject_kind='task_run' AND session_id=?",
+            (session_id,),
+        ).fetchall()
+    return {row["task_id"]: dict(row) for row in rows}
+
+
+def _task(task_id: int) -> dict:
+    from app import tm
+
+    with tm._conn() as connection:
+        return tm.get_task_by_id(connection, task_id)
+
+
+async def _worker_after_continue(monkeypatch, tmp_path, name: str):
+    """Real repo; task 5 bound with an open run, merged with `continue`; task 6 queued."""
+    import app.workspace as workspace
+    from app import tm
+
+    _init_db()
+    repo = _make_git_scope(monkeypatch, tmp_path)
+    scope = str(repo)
+    with tm._conn() as connection:
+        tm.ensure_project(connection, "project", scope=scope)
+        current = seed_task(connection, "project", "Current", par_number=5)
+        following = seed_task(connection, "project", "Next", par_number=6)
+    current_ref = tm.public_task_ref(current)
+    worktree = workspace.create_worktree(scope, name, task_id=current_ref)
+    _save_worker(
+        session_id=name, task_id=current_ref, scope=scope,
+        worktree_path=worktree.path, branch=worktree.branch,
+    )
+    tm.bind_task_to_session(scope, name, current_ref)
+    head = _commit_file(worktree.path, "work.txt", "first phase")
+    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)
+
+    import app.routes.sessions as sessions_route
+
+    merged = await sessions_route.execute_merge_session(
+        session_id=found.id,
+        expected_name=found.name,
+        expected_scope=found.scope,
+        expected_branch=found.branch,
+        expected_head=head,
+        req={"scope": scope, "merge_schema_version": 2, "task_outcome": "continue"},
+    )
+    assert merged["ok"] is True, merged
+    assert _rev(worktree.path) == _rev(repo, "main")
+    assert _runs(name)[current_ref]["status"] == "requested"
+    return repo, worktree, current, following
+
+
+async def _switch(name: str, repo, task_ref: str, **extra):
+    import app.routes.sessions as sessions_route
+
+    return await sessions_route.switch_branch(
+        name, {"scope": str(repo), "task_id": task_ref, **extra},
+    )
+
+
+def _assert_still_bound(name, current, following):
+    from app import tm
+    from app.db import get_session
+
+    current_ref = tm.public_task_ref(current)
+    kept = _task(current["id"])
+    assert (kept["status"], kept["worker_session_id"]) == ("in_progress", name)
+    assert _runs(name)[current_ref]["status"] == "requested"
+    queued = _task(following["id"])
+    assert (queued["status"], queued["worker_session_id"]) == ("new", None)
+    assert get_session(name)["task_id"] == current_ref
+
+
+@pytest.mark.asyncio
+async def test_switch_releases_clean_worker_and_requeues_previous_task(monkeypatch, tmp_path):
+    from app import tm
+    from app.db import get_session
+
+    name = "release-worker"
+    repo, worktree, current, following = await _worker_after_continue(
+        monkeypatch, tmp_path, name,
+    )
+    current_ref, next_ref = tm.public_task_ref(current), tm.public_task_ref(following)
+
+    result = await _switch(name, repo, next_ref)
+
+    assert result.get("ok") is True, result
+    released = _task(current["id"])
+    assert (released["status"], released["worker_session_id"]) == ("new", None)
+    runs = _runs(name)
+    assert (runs[current_ref]["status"], runs[current_ref]["failure_code"]) == (
+        "interrupted", "binding_released",
+    )
+    assert runs[next_ref]["status"] == "requested"
+    assigned = _task(following["id"])
+    assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)
+    lifecycle = get_session(name)
+    assert (lifecycle["task_id"], lifecycle["branch"]) == (next_ref, f"task-{next_ref}/{name}")
+    assert result["task_status"]["previous_tasks"] == [
+        {"task": current_ref, "outcome": "released"},
+    ]
+
+
+@pytest.mark.asyncio
+async def test_switch_with_complete_previous_closes_task_as_done_with_note(
+    monkeypatch, tmp_path,
+):
+    from app import tm
+
+    name = "done-worker"
+    repo, worktree, current, following = await _worker_after_continue(
+        monkeypatch, tmp_path, name,
+    )
+    current_ref, next_ref = tm.public_task_ref(current), tm.public_task_ref(following)
+    head = _rev(worktree.path)
+
+    missing_note = await _switch(name, repo, next_ref, complete_previous=True)
+    assert missing_note.status_code == 400
+    _assert_still_bound(name, current, following)
+
+    result = await _switch(
+        name, repo, next_ref,
+        complete_previous=True, acceptance_note="phase merged in continue; verified on main",
+    )
+
+    assert result.get("ok") is True, result
+    closed = _task(current["id"])
+    assert (closed["status"], closed["worker_session_id"]) == ("done", None)
+    run = _runs(name)[current_ref]
+    assert run["status"] == "completed"
+    assert run["verdict_value"] == "phase merged in continue; verified on main"
+    assert run["worker_head"] == head
+    assigned = _task(following["id"])
+    assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize("held", ["uncommitted", "unmerged_commit"])
+@pytest.mark.parametrize("mode", ["plain", "force", "complete_previous"])
+async def test_switch_keeps_binding_while_worker_holds_unlanded_work(
+    monkeypatch, tmp_path, held, mode,
+):
+    from app import tm
+
+    name = "holding-worker"
+    repo, worktree, current, following = await _worker_after_continue(
+        monkeypatch, tmp_path, name,
+    )
+    if held == "uncommitted":
+        (Path(worktree.path) / "pending.txt").write_text("pending")
+    else:
+        _commit_file(worktree.path, "later.txt", "second phase")
+    extra = {
+        "plain": {},
+        "force": {"force": True},
+        "complete_previous": {"complete_previous": True, "acceptance_note": "claimed done"},
+    }[mode]
+
+    result = await _switch(name, repo, tm.public_task_ref(following), **extra)
+
+    if mode == "complete_previous":
+        assert result.status_code == 409
+    else:
+        assert result.get("ok") is not True, result
+    _assert_still_bound(name, current, following)


## LATER FIX 6ba1141c91 (13.0 days later): V-736: #V-736: restore CI on main
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-736: #V-736: restore CI on main

Orchestra-Operation: 8b660deb-845c-446d-923b-e05e589ee683


diff --git a/app/db.py b/app/db.py
index fafad79cf..83981113d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -2372,24 +2372,24 @@ def usage_exchange_rate(hours: int = 72, min_five_hour_pct: float = 30.0) -> dic
 def _usage_providers_from_row(row: dict) -> dict:
     providers = json.loads(row.pop("provider_usage", "{}") or "{}")
     if providers:
         return providers
     windows = []
     # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
     # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
     fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
-    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct == 0):
+    if fh_pct is not None:
         windows.append({
             "id": "five_hour", "label": "5h",
             "utilization": fh_pct,
             "window_minutes": 300,
             "resets_at": row.get("five_hour_resets_at") or None,
         })
-    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct == 0):
+    if sd_pct is not None:
         windows.append({
             "id": "seven_day", "label": "7d",
             "utilization": sd_pct,
             "window_minutes": 10080,
             "resets_at": row.get("seven_day_resets_at") or None,
         })
     return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}
 
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 9afc2c5e5..a7de05d73 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -3287,16 +3287,27 @@ async def switch_branch(name: str, req: dict):
                                 "error": (
                                     f"cannot close task {previous_task_id} as done: "
                                     f"{held_work['reason']}; merge or discard that work first"
                                 ),
                                 "waited_seconds": round(waited_seconds, 2),
                             },
                             status_code=409,
                         )
+                    elif force:
+                        return JSONResponse(
+                            {
+                                "error": (
+                                    f"cannot switch away from task {previous_task_id}: "
+                                    f"{held_work['reason']} — merge or discard that work first"
+                                ),
+                                "waited_seconds": round(waited_seconds, 2),
+                            },
+                            status_code=409,
+                        )
                 try:
                     verdict = await asyncio.to_thread(
                         _existing_branch_verdict, worktree_path, new_branch,
                         found.scope or scope, force,
                     )
                     if verdict.get("error"):
                         return JSONResponse(
                             {**verdict, "waited_seconds": round(waited_seconds, 2)},
diff --git a/tests/test_explainer_video.py b/tests/test_explainer_video.py
index c883ddff5..81844256d 100644
--- a/tests/test_explainer_video.py
+++ b/tests/test_explainer_video.py
@@ -7,16 +7,27 @@ import importlib.util
 from pathlib import Path
 
 ROOT = Path(__file__).resolve().parents[1]
 spec = importlib.util.spec_from_file_location("explainer_make", ROOT / "scripts/explainer_video/make.py")
 make = importlib.util.module_from_spec(spec)
 spec.loader.exec_module(make)
 
 
+def _mock_tts_installation(tmp_path, monkeypatch):
+    python = tmp_path / "venv" / "bin" / "python"
+    python.parent.mkdir(parents=True)
+    python.write_text("test interpreter placeholder")
+    model = tmp_path / "vosk-model"
+    model.mkdir()
+    (model / "model.onnx").touch()
+    monkeypatch.setattr(make, "TTS_PYTHON", python)
+    monkeypatch.setattr(make, "TTS_MODEL", model)
+
+
 def test_deepgram_digits_latin_and_glued_words_match_screen_text():
     heard = make.tokens("а deepinfra иstreamlake держат кэш 7680 токенов")
     say, sub = "А Дип Инфра и Стрим Лейк держат кеш", "А DeepInfra и StreamLake держат кеш, 7 680 токенов"
     assert all(h is not None for h in make.align([sub], heard)[0])
     assert None in make.align([say], heard)[0]  # транслитерацию Deepgram пишет латиницей
 
 
 def test_missing_word_is_reported_per_phrase():
@@ -83,16 +94,17 @@ def test_english_voice_reads_latin_and_digits_but_rejects_cyrillic():
     with pytest.raises(SystemExit):
         make.check_steps(ok, "ru")
 
 
 def test_ruaccent_marks_text_before_it_reaches_vosk_synthesis(tmp_path, monkeypatch):
     import json
     import wave
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills"])
     monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "Лимит", "say": "История лимита.", "sub": None, "hold": None}])
     before_path = list(make.sys.path)
     jobs = []
     accent_calls = []
 
     def fake_accent_process(argv, **kwargs):
         phrases = json.loads(kwargs["input"])
@@ -185,31 +197,33 @@ def test_english_cli_branch_does_not_load_or_run_ruaccent(monkeypatch, tmp_path)
 
     monkeypatch.setattr(make, "synthesize", synthesize)
     monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
     monkeypatch.setattr(make, "voice_track", lambda *_: None)
     monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
     make.main()
 
 
-def test_missing_ruaccent_fails_with_install_command(monkeypatch):
+def test_missing_ruaccent_fails_with_install_command(tmp_path, monkeypatch):
     import pytest
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     def missing(argv, **_kwargs):
         return make.subprocess.CompletedProcess(argv, 2, stdout="", stderr="RUACCENT_NOT_INSTALLED")
 
     monkeypatch.setattr(make.subprocess, "run", missing)
     with pytest.raises(SystemExit, match="ruaccent==1.5.8.3"):
         make.mark_stress([{"say": "Фраза."}], "ru", enabled=True)
 
 
 def test_cache_key_changes_when_accented_text_changes(tmp_path, monkeypatch):
     import json
     import wave
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     jobs_seen = []
 
     def fake_run(*argv, **kwargs):
         if "tts_worker.py" in argv[1]:
             jobs = json.loads(kwargs["input"])
             jobs_seen.extend(job["text"] for job in jobs)
             for job in jobs:
                 with wave.open(job["out"], "wb") as output:
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index b6909cada..0c6647582 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -11,17 +11,17 @@ import os
 import re
 import socket
 import subprocess
 import tempfile
 import sys
 import time
 import urllib.error
 import urllib.request
-from urllib.parse import quote
+from urllib.parse import parse_qs, quote, urlsplit
 from datetime import datetime, timezone
 from pathlib import Path
 
 import pytest
 from playwright.sync_api import Browser, Page, expect, sync_playwright
 from playwright.sync_api import TimeoutError as PlaywrightTimeout
 from starlette.requests import Request
 
@@ -56,29 +56,16 @@ def _load_i18n(page: Page) -> None:
 _DASHBOARD_START_TIMEOUT_S = 120.0
 HTML_ARTIFACT_CSP = (
     "sandbox allow-scripts; "
     "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
     "connect-src 'none'"
 )
 
 
-def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
-    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
-    html_branch = source.split("if (/\\.html?$/i.test(path)) {", 1)[1].split(
-        "return;", 1,
-    )[0]
-    match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
-
-    assert match
-    assert "openBtn.href = rawUrl;" in html_branch
-    assert set(match.group(1).split()) == {"allow-scripts"}
-    assert "allow-same-origin" not in match.group(1)
-
-
 def test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result():
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     helper = source.split("function _historyTransferMessage", 1)[1].split(
         "async function _showModelPicker", 1,
     )[0]
     picker = source.split("async function _showModelPicker", 1)[1].split(
         "function updateAgentInfo", 1,
     )[0]
@@ -205,16 +192,40 @@ def test_raw_video_supports_range_and_full_download(tmp_path, monkeypatch):
     assert cached.status_code == 304
     assert cached.content == b""
     assert cached_by_date.status_code == 304
     assert replaced.status_code == 200
     assert replaced.content == b"rewritten media content"
     assert replaced.headers["etag"] != full.headers["etag"]
 
 
+def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox(
+    dashboard_browser: Browser,
+):
+    page = dashboard_browser.new_page()
+    _route_frontend_sources(page)
+    page.route(
+        "**/api/files/raw*",
+        lambda route: route.fulfill(status=200, content_type="text/html", body="<p>preview</p>"),
+    )
+    _goto_dashboard(page)
+    page.wait_for_function("() => typeof openFilePreview === 'function'")
+    page.evaluate("openFilePreview('/tmp/harness.html')")
+
+    iframe = page.locator("#file-preview-content iframe")
+    expect(iframe).to_have_count(1)
+    assert set((iframe.get_attribute("sandbox") or "").split()) == {"allow-scripts"}
+    open_link = page.locator("#file-preview-open")
+    assert open_link.get_attribute("target") == "_blank"
+    raw_url = urlsplit(open_link.get_attribute("href") or "")
+    assert raw_url.path == "/api/files/raw"
+    assert parse_qs(raw_url.query)["path"] == ["/tmp/harness.html"]
+    page.close()
+
+
 def _dashboard_base() -> str:
     if not _DASHBOARD_ORIGIN:
         pytest.fail("dashboard fixture did not start — dashboard_browser is required")
     return _DASHBOARD_ORIGIN
 
 
 def _free_port() -> int:
     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
@@ -1724,17 +1735,19 @@ def test_send_file_single_keeps_existing_rendering(
             null,
             null,
             {tool_use_id: 'send-file-test'},
         );
     }""")
 
     card = page.locator('[data-tool-raw-name="mcp__orchestra__send_file"]')
     expect(card.locator(".sf-file-list")).to_have_count(0)
-    expect(card.locator("button")).to_have_count(2)
+    expect(card.locator("button")).to_have_count(3)
+    expect(card.get_by_role("button", name=re.compile("Download"))).to_have_count(1)
+    expect(card.get_by_role("button", name=re.compile("Open"))).to_have_count(1)
     expect(card.locator(".sf-actions")).to_have_count(0)
     page.close()
 
 
 def _open_tool_correlation_page(
     browser: Browser,
     compact_mode: bool,
     source_path: Path | None = None,
diff --git a/tests/test_message_delivery_receipts_380.py b/tests/test_message_delivery_receipts_380.py
index 164f5cf24..64259595e 100644
--- a/tests/test_message_delivery_receipts_380.py
+++ b/tests/test_message_delivery_receipts_380.py
@@ -1476,19 +1476,19 @@ async def test_t380_r7_accept_while_runner_exits_cannot_lose_wake(
     registry = getattr(module, "_target_runner_tasks", None)
     assert isinstance(registry, dict), "#380 missing behavior: per-target runner registry"
     empty_seen = threading.Event()
     allow_empty_return = threading.Event()
     inserted = []
     thread_failures = []
     gated_once = False
 
-    def gated_next(target_session_id):
+    def gated_next(target_session_id, *, connection=None):
         nonlocal gated_once
-        row = next_delivery(target_session_id)
+        row = next_delivery(target_session_id, connection=connection)
         if row is None and not gated_once:
             gated_once = True
             empty_seen.set()
             assert allow_empty_return.wait(2), "#380 lost-wake insertion thread stalled"
         return row
 
     monkeypatch.setattr(module, "_next_target_delivery", gated_next)
     manager = _ImmediateManager()
diff --git a/tests/test_model_text_control_flow.py b/tests/test_model_text_control_flow.py
index 2591c6a9c..26ff6d9c7 100644
--- a/tests/test_model_text_control_flow.py
+++ b/tests/test_model_text_control_flow.py
@@ -183,17 +183,18 @@ def test_claude_adapter_keeps_primary_limit_signal(status):
     from app.backend_claude import ClaudeBackend
     backend = ClaudeBackend(model='claude-sonnet-5[1m]', cwd='/tmp')
     converted = backend._convert(RateLimitEvent(
         rate_limit_info=RateLimitInfo(status=status, rate_limit_type='seven_day',
                                      overage_status='rejected', resets_at=2000000000),
         uuid='signal-id', session_id='session'))
     event = next(e for e in converted if e.type == 'provider_limit')
     assert event.metadata == {'status': status, 'rate_limit_type': 'seven_day',
-                             'resets_at': 2000000000, 'overage_status': 'rejected', 'event_id': 'signal-id'}
+                             'resets_at': 2000000000, 'overage_status': 'rejected',
+                             'event_id': 'signal-id', 'raw': {}}
 
 
 @pytest.mark.asyncio
 async def test_limit_arriving_during_admission_stops_retry_before_submit(session):
     from app.events import MessageProvenance
     entered = asyncio.Event()
     release = asyncio.Event()
     async def admission(_model):
diff --git a/tests/test_switch_after_continue_620.py b/tests/test_switch_after_continue_620.py
index c02a85348..e469c0049 100644
--- a/tests/test_switch_after_continue_620.py
+++ b/tests/test_switch_after_continue_620.py
@@ -117,17 +117,17 @@ async def test_switch_releases_clean_worker_and_requeues_previous_task(monkeypat
 
     result = await _switch(name, repo, next_ref)
 
     assert result.get("ok") is True, result
     released = _task(current["id"])
     assert (released["status"], released["worker_session_id"]) == ("new", None)
     runs = _runs(name)
     assert (runs[current_ref]["status"], runs[current_ref]["failure_code"]) == (
-        "interrupted", "binding_released",
+        "interrupted", "task_superseded",
     )
     assert runs[next_ref]["status"] == "requested"
     assigned = _task(following["id"])
     assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)
     lifecycle = get_session(name)
     assert (lifecycle["task_id"], lifecycle["branch"]) == (next_ref, f"task-{next_ref}/{name}")
     assert result["task_status"]["previous_tasks"] == [
         {"task": current_ref, "outcome": "released"},
@@ -186,13 +186,13 @@ async def test_switch_keeps_binding_while_worker_holds_unlanded_work(
     extra = {
         "plain": {},
         "force": {"force": True},
         "complete_previous": {"complete_previous": True, "acceptance_note": "claimed done"},
     }[mode]
 
     result = await _switch(name, repo, tm.public_task_ref(following), **extra)
 
-    if mode == "complete_previous":
+    if mode in {"force", "complete_previous"}:
         assert result.status_code == 409
     else:
         assert result.get("ok") is not True, result
     _assert_still_bound(name, current, following)
diff --git a/tests/test_usage_analytics_frontend.py b/tests/test_usage_analytics_frontend.py
index e3b9cec42..7dde01715 100644
--- a/tests/test_usage_analytics_frontend.py
+++ b/tests/test_usage_analytics_frontend.py
@@ -765,17 +765,17 @@ def test_new_frontend_remains_compatible_with_old_analytics_payload(browser):
     )
 
     page.evaluate("openAnalyticsModal()")
     expect(page.locator(".analytics-kpi-grid > article:first-child")).to_contain_text(
         "716 priced turns"
     )
 
     page.locator('[data-analytics-view="agents"]').click()
-    expect(page.locator("#analytics-agent-table")).to_contain_text("$1,74")
+    expect(page.locator("#analytics-agent-table")).to_contain_text("$1.74")
 
     page.locator('[data-analytics-view="efficiency"]').click()
     expect(page.locator(".analytics-model-list")).to_contain_text("60.8%")
     page.close()
 
 
 def test_modal_has_no_document_overflow_at_390px(browser):
     page = _page(browser, width=390, height=844)
diff --git a/tests/test_usage_readiness.py b/tests/test_usage_readiness.py
index c72554f58..5d9fee21f 100644
--- a/tests/test_usage_readiness.py
+++ b/tests/test_usage_readiness.py
@@ -198,24 +198,24 @@ async def test_readiness_endpoint_returns_the_execution_time_decision(isolated_u
     assert result["state"] == "available" and result["allowed"] is True
     assert result["progress"] is None and result["limit_pct"] is None
     assert result["hard_limit_pct"] == 99.0
 
 
 @pytest.mark.asyncio
 async def test_readiness_endpoint_blocks_above_the_line(isolated_usage):
     data = _anthropic(95)
-    # Ровно середина недельного окна: линия 55.5%, факт 95% — выше неё.
+    # В середине окна линия сдвинута на восемь часов: 59.8333%, факт 95% — выше неё.
     data["seven_day"]["resets_at"] = datetime.fromtimestamp(
         NOW + 10080 * 60 / 2, timezone.utc,
     ).isoformat()
     system._usage_cache.update({"data": data, "ts": NOW})
     result = await system.usage_readiness("claude-opus-5[1m]")
     assert result["state"] == "blocked" and result["allowed"] is False