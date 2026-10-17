# Candidate cand-42

## ORIGIN commit 2a048e6161 (2026-09-03): #465: research taskless adhoc merge deadlock
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/manager.py b/app/manager.py
index 6c499e6ea..bd764a225 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -965,18 +965,39 @@ class SessionManager:
 
             return session
 
         finalize_task = asyncio.create_task(finalize())
         await _wait_owned_task(finalize_task)
         return finalize_task.result()
 
     async def _auto_switch_before_delivery(self, session: AgentSession) -> None:
+        if not getattr(session, "loaded", True):
+            durable = await asyncio.to_thread(get_session, session.id)
+            if durable:
+                session.branch = durable.get("branch") or session.branch
+                session.base_branch = durable.get("base_branch") or session.base_branch
+                session.task_id = durable.get("task_id") or ""
+                session.needs_switch = bool(durable.get("needs_switch") or 0)
         if not session.needs_switch:
             return
+        if str(session.task_id or ""):
+            from app.tm import task_binding_requires_quarantine
+
+            blocked = await asyncio.to_thread(
+                task_binding_requires_quarantine,
+                session.scope,
+                session.id,
+                str(session.task_id),
+            )
+            if blocked:
+                raise RuntimeError(
+                    f"worker lifecycle is quarantined for task #{session.task_id}; "
+                    "repair the task/branch binding before delivery"
+                )
         if session.status != AgentStatus.IDLE:
             raise RuntimeError(
                 f"worker is {session.status.value} — cannot auto-switch before delivery"
             )
         if not session.worktree_path:
             raise RuntimeError("auto-switch failed: session has no worktree")
 
         async with session._lifecycle_lock:
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index a50bc90ca..2cbbad6ab 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2774,42 +2774,51 @@ async def resolve_merge_operation(operation_id: str, reason: str) -> CallToolRes
 
 
 @mcp.tool()
 async def switch_worker_branch(
     name: str,
     task_id: str,
     from_ref: str = "",
     force: bool = False,
+    promote_current: bool = False,
     owned_dirs: str = "",
 ) -> str:
     """After merge, switch worker to a new branch for a new task.
     from_ref — optional local base override; empty uses the worker's persisted base.
     force=True explicitly discards committed content not verified in the base.
+    promote_current=True preserves and assigns committed taskless adhoc work.
     owned_dirs — optional JSON array replacing the worker's ownership on a new task;
     omitted or [] clears it.
     Worker must be idle with clean working tree."""
     payload = {
         "scope": SCOPE,
         "task_id": task_id,
         "from_ref": from_ref,
         "force": force,
+        "promote_current": promote_current,
     }
     if owned_dirs:
         try:
             parsed_owned_dirs = json.loads(owned_dirs)
         except (TypeError, ValueError) as error:
             return f"Switch failed: owned_dirs is not valid JSON: {error}"
         if not isinstance(parsed_owned_dirs, list):
             return "Switch failed: owned_dirs must be a JSON array"
         payload["owned_dirs"] = parsed_owned_dirs
     result = await _api("POST", f"/api/sessions/{name}/switch-branch",
                         json=payload)
     if isinstance(result, dict) and result.get("error"):
         return f"Switch failed: {result['error']}"
+    if (
+        isinstance(result, dict)
+        and result.get("ok")
+        and result.get("state") == "promoted_current_work"
+    ):
+        return f"Promoted current work to branch {result.get('branch', '?')}"
     if isinstance(result, dict) and result.get("ok"):
         return f"Switched to branch {result.get('branch', '?')}"
     if isinstance(result, dict) and result.get("conflicts"):
         return f"Merge conflict with base branch on: {', '.join(result['conflicts'])}"
     return f"Switch result: {result}"
 
 
 @mcp.tool()
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 8ffc26435..37a94a45b 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -2377,27 +2377,292 @@ async def execute_merge_session(
                         if not quarantine_status["ok"]:
                             switch_result["persistence_error"] = (
                                 quarantine_status["error"]
                             )
                 result["switch"] = switch_result
             return result
 
 
+async def _promote_current_work_for_task(
+    *,
+    found,
+    task_identity: dict,
+    par: str,
+    scope: str,
+    worktree_path: str,
+    new_branch: str,
+    from_ref: str,
+    requested_owned_dirs: list[str] | None,
+    previous_branch: str,
+    previous_base_branch: str,
+    previous_owned_dirs: list[str],
+    waited_seconds: float,
+):
+    from app import tm as _tm
+    from app.workspace import (
+        inspect_worktree_identity,
+        promote_worktree_branch,
+        rollback_promoted_worktree_branch,
+    )
+
+    durable = await asyncio.to_thread(get_session_row, found.id)
+    if not durable or durable.get("status") == "archived":
+        return JSONResponse({"error": "session is not available for promotion"}, status_code=409)
+    if durable.get("status") != "idle":
+        return JSONResponse({"error": "worker must be idle for promotion"}, status_code=409)
+    durable_branch = str(durable.get("branch") or "")
+    if str(durable.get("task_id") or ""):
+        return JSONResponse({"error": "session is already bound to a task"}, status_code=409)
+    if bool(durable.get("needs_switch")):
+        return JSONResponse(
+            {"error": "normal completed session cannot promote its previous branch"},
+            status_code=409,
+        )
+    if durable_branch != previous_branch or str(getattr(found, "branch", "") or "") != previous_branch:
+        return JSONResponse({"error": "session branch changed before promotion"}, status_code=409)
+    try:
+        actual_branch, worker_head = await asyncio.to_thread(
+            inspect_worktree_identity, worktree_path,
+        )
+    except RuntimeError as error:
+        return JSONResponse({"error": str(error)}, status_code=409)
+    if actual_branch != durable_branch:
+        return JSONResponse(
+            {"error": f"durable branch {durable_branch} disagrees with Git branch {actual_branch}"},
+            status_code=409,
+        )
+    try:
+        await asyncio.to_thread(
+            _tm.validate_task_promotion_target,
+            task_identity,
+            scope=scope,
+            session_id=found.id,
+            expected_branch=durable_branch,
+        )
+    except ValueError as error:
+        return JSONResponse({"error": str(error)}, status_code=409)
+
+    latest = await asyncio.to_thread(get_session_row, found.id)
+    if (
+        not latest
+        or latest.get("status") != "idle"
+        or str(latest.get("task_id") or "")
+        or bool(latest.get("needs_switch"))
+        or str(latest.get("branch") or "") != durable_branch
+        or str(latest.get("scope") or "").rstrip("/") != scope.rstrip("/")
+    ):
+        return JSONResponse(
+            {"error": "session lifecycle changed before promotion"}, status_code=409,
+        )
+
+    promotion = await asyncio.to_thread(
+        promote_worktree_branch,
+        worktree_path,
+        new_branch,
+        from_ref=from_ref,
+        expected_branch=durable_branch,
+        expected_head=worker_head,
+    )
+    promotion["waited_seconds"] = round(waited_seconds, 2)
+    if not promotion.get("ok"):
+        if promotion.get("state") == "rollback_failed":
+            promotion["lifecycle_status"] = await _persist_lifecycle_quarantine(
+                found,
+                branch=str(promotion.get("branch") or durable_branch),
+                base_branch=from_ref,
+                task_id=par,
+                needs_switch=True,
+            )
+        return promotion
+
+    try:
+        await manager.transition_lifecycle(
+            found,
+            branch=new_branch,
+            base_branch=from_ref,
+            task_id=par,
+            needs_switch=True,
+            owned_dirs=requested_owned_dirs,
+        )
+    except Exception as error:
+        rollback = await asyncio.to_thread(
+            rollback_promoted_worktree_branch,
+            worktree_path,
+            promoted_branch=new_branch,
+            previous_branch=durable_branch,
+            expected_head=worker_head,
+        )
+        if not rollback.get("ok"):
+            quarantine = await _persist_lifecycle_quarantine(
+                found, branch=rollback.get("branch") or new_branch,
+                base_branch=from_ref, task_id=par, needs_switch=True,
+            )
+            return {
+                **promotion,
+                "ok": False,
+                "state": "rollback_failed",
+                "error": f"promotion persistence failed: {err_text(error)}; {rollback.get('error', '')}",
+                "rollback": rollback,
+                "lifecycle_status": quarantine,
+            }
+        return {
+            **promotion,
+            "ok": False,
+            "state": "promotion_persistence_failed",
+            "branch": rollback["branch"],
+            "head": rollback["head"],
+            "error": f"promotion persistence failed: {err_text(error)}",
+            "rollback": rollback,
+        }
+
+    task_status = None
+    task_error = None
+    try:
+        task_status = await asyncio.to_thread(
+            _tm.api_update_task_if_current,
+            task_identity,
+            status="in_progress",
+            expected_status="new",
+            require_unreserved=True,
+        )
+    except Exception as error:
+        task_error = error
+
+    debt = (task_status or {}).get("projection_debt") or {}
+    partial = bool(
+        task_error is not None
+        or debt
+        or (task_status or {}).get("shadow_match") is False
+    )
+    complete = bool(
+        task_error is None
+        and task_status
+        and task_status.get("ok")
+        and not partial
+    )
+    if not complete and partial:
+        message = err_text(task_error) if task_error is not None else str(
+            (task_status or {}).get("error") or debt.get("message") or "task binding is partial"
+        )
+        return {
+            **promotion,
+            "ok": False,
+            "state": (
+                "promotion_binding_unknown" if task_error is not None
+                else "promotion_binding_partial"
+            ),
+            "error": message,
+            "task_status": task_status or {"ok": False, "error": message},
+            "lifecycle_status": {"ok": True, "quarantined": True},
+        }
+    if not complete:
+        rollback = await asyncio.to_thread(
+            rollback_promoted_worktree_branch,
+            worktree_path,
+            promoted_branch=new_branch,
+            previous_branch=durable_branch,
+            expected_head=worker_head,
+        )
+        message = str((task_status or {}).get("error") or "task binding was rejected")
+        if rollback.get("ok"):
+            try:
+                await manager.transition_lifecycle(
+                    found,
+                    branch=durable_branch,
+                    base_branch=previous_base_branch,
+                    task_id="",
+                    needs_switch=False,
+                    owned_dirs=previous_owned_dirs,
+                )
+            except Exception as restore_error:
+                quarantine = await _persist_lifecycle_quarantine(
+                    found, branch=durable_branch, base_branch=previous_base_branch,
+                    task_id=par, needs_switch=True,
+                )
+                return {
+                    **promotion,
+                    "ok": False,
+                    "state": "rollback_failed",
+                    "branch": durable_branch,
+                    "head": worker_head,
+                    "error": f"{message}; lifecycle restore failed: {err_text(restore_error)}",
+                    "rollback": rollback,
+                    "lifecycle_status": quarantine,
+                }
+            return {
+                **promotion,
+                "ok": False,
+                "state": "promotion_binding_failed",
+                "branch": durable_branch,
+                "head": worker_head,
+                "error": message,
+                "rollback": rollback,
+                "task_status": task_status,
+            }
+        quarantine = await _persist_lifecycle_quarantine(
+            found,
+            branch=str(rollback.get("branch") or new_branch),
+            base_branch=from_ref,
+            task_id=par,
+            needs_switch=True,
+        )
+        return {
+            **promotion,
+            "ok": False,
+            "state": "rollback_failed",
+            "error": f"{message}; {rollback.get('error', '')}",
+            "rollback": rollback,
+            "task_status": task_status,
+            "lifecycle_status": quarantine,
+        }
+
+    try:
+        await manager.transition_lifecycle(
+            found,
+            branch=new_branch,
+            base_branch=from_ref,
+            task_id=par,
+            needs_switch=False,
+            owned_dirs=requested_owned_dirs,
+        )
+    except Exception as error:
+        quarantine = await _persist_lifecycle_quarantine(
+            found, branch=new_branch, base_branch=from_ref,
+            task_id=par, needs_switch=True,
+        )
+        return {
+            **promotion,
+            "ok": False,
+            "state": "promotion_binding_partial",
+            "error": f"task bound but lifecycle finalization failed: {err_text(error)}",
+            "task_status": task_status,
+            "lifecycle_status": quarantine,
+        }
+    return {**promotion, "task_status": task_status}
+
+
 @router.post("/api/sessions/{name}/switch-branch")
 async def switch_branch(name: str, req: dict):
     from app.workspace import switch_worktree_branch
     from app import tm as _tm
     scope = req.get("scope", "")
     task_id = req.get("task_id", "")
     force = req.get("force", False)
+    promote_current = req.get("promote_current", False)
     if not task_id:
         return JSONResponse({"error": "task_id required"}, status_code=400)
     if not isinstance(force, bool):
         return JSONResponse({"error": "force must be a boolean"}, status_code=400)
+    if not isinstance(promote_current, bool):
+        return JSONResponse({"error": "promote_current must be a boolean"}, status_code=400)
+    if promote_current and force:
+        return JSONResponse(
+            {"error": "promote_current cannot be combined with force"}, status_code=400,
+        )
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     scope = (getattr(found, "scope", "") or scope).rstrip("/")
     try:
         task_identity = await asyncio.to_thread(
             _tm.resolve_scoped_task_identity, scope, task_id,
         )
@@ -2454,16 +2719,31 @@ async def switch_branch(name: str, req: dict):
                             {
                                 "error": (
                                     f"worker is {found.status.value} — "
                                     "wait for idle before switch"
                                 )
                             },
                             status_code=400,
                         )
+                if promote_current:
+                    return await _promote_current_work_for_task(
+                        found=found,
+                        task_identity=task_identity,
+                        par=par,
+                        scope=scope,
+                        worktree_path=worktree_path,
+                        new_branch=new_branch,
+                        from_ref=from_ref,
+                        requested_owned_dirs=requested_owned_dirs,
+                        previous_branch=previous_branch,
+                        previous_base_branch=previous_base_branch,
+                        previous_owned_dirs=previous_owned_dirs,
+                        waited_seconds=waited_seconds,
+                    )
                 try:
                     verdict = await asyncio.to_thread(
                         _existing_branch_verdict, worktree_path, new_branch,
                         found.scope or scope, force,
                     )
                     if verdict.get("error"):
                         return JSONResponse(
                             {**verdict, "waited_seconds": round(waited_seconds, 2)},
diff --git a/app/tm.py b/app/tm.py
index 0b857555e..5559d483c 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -1681,21 +1681,121 @@ def _validate_inferred_task_worker(
     if len(rows) != 1 or rows[0]["id"] != worker_session_id:
         owners = ", ".join(row["id"] for row in rows) or "none"
         raise ValueError(
             f"task #{task['par_number']} session binding changed before status update: "
             f"expected '{worker_session_id}', found {owners}"
         )
 
 
+def _task_claim_precondition_error(
+    conn: sqlite3.Connection,
+    task: dict,
+    *,
+    expected_status: str,
+    require_unreserved: bool,
+) -> str:
+    if expected_status and task["status"] != expected_status:
+        return (
+            f"promotion target must be {expected_status} "
+            f"(found {task['status']})"
+        )
+    if expected_status and task.get("worker_session_id"):
+        return (
+            f"promotion target task #{task['par_number']} is already owned by "
+            f"session '{task['worker_session_id']}'"
+        )
+    if require_unreserved:
+        reservation = conn.execute(
+            "SELECT operation_id FROM tm_task_reservations WHERE task_id=?",
+            (task["id"],),
+        ).fetchone()
+        if reservation:
+            return (
+                f"promotion target task #{task['par_number']} is reserved by "
+                f"operation {reservation['operation_id']}"
+            )
+    return ""
+
+
+def validate_task_promotion_target(
+    identity: TaskIdentity,
+    *,
+    scope: str,
+    session_id: str,
+    expected_branch: str,
+) -> None:
+    """Fail early for UX; the mutation owner repeats these checks transactionally."""
+    with _TASK_BINDING_LOCK, _conn() as conn:
+        conn.execute("BEGIN IMMEDIATE")
+        try:
+            session = conn.execute(
+                "SELECT id, scope, status, task_id, needs_switch, branch FROM sessions "
+                "WHERE id=?",
+                (session_id,),
+            ).fetchone()
+            if not session or session["status"] == "archived":
+                raise ValueError("session is not available for promotion")
+            if session["scope"].rstrip("/") != scope.rstrip("/"):
+                raise ValueError("session promotion scope changed")
+            if str(session["task_id"] or ""):
+                raise ValueError("session is already bound to a task")
+            if bool(session["needs_switch"]):
+                raise ValueError("normal completed session cannot promote its previous branch")
+            if str(session["branch"] or "") != expected_branch:
+                raise ValueError("session branch changed before promotion")
+            project = get_project_by_scope(conn, scope.rstrip("/"))
+            if not project or project["id"] != identity["project_id"]:
+                raise ValueError("promotion target is outside the session project")
+            task = get_task_by_id(conn, identity["id"])
+            if not task:
+                raise ValueError("promotion target disappeared")
+            if (
+                task["project_id"] != identity["project_id"]
+                or task["par_number"] != identity["par_number"]
+                or task["sync_revision"] != identity["sync_revision"]
+            ):
+                raise ValueError("promotion target identity changed")
+            error = _task_claim_precondition_error(
+                conn, task, expected_status="new", require_unreserved=True,
+            )
+            if error:
+                raise ValueError(error)
+            conn.commit()
+        except Exception:
+            conn.rollback()
+            raise
+
+
+def task_binding_requires_quarantine(
+    scope: str, session_id: str, task_ref: str,
+) -> bool:
+    """Distinguish incomplete live ownership from a stale completed-task binding."""
+    with _conn() as conn:
+        project = get_project_by_scope(conn, scope.rstrip("/"))
+        if not project:
+            # Pre-task-tracker sessions legitimately carry stale task ids; their established
+            # auto-switch path is the only recovery and has no task row to protect.
+            return False
+        task = resolve_task_ref(conn, task_ref, project["id"])
+        if not task:
+            return True
+        return not (
+            task["status"] == "done"
+            and not task.get("worker_session_id")
+        )
+
+
 def api_update_task_if_current(
     identity: TaskIdentity,
     *,
     status: str,
     worker_session_id: str | None = None,
+    expected_status: str = "",
+    require_unreserved: bool = False,
 ) -> dict:
     """Update a prevalidated task only while its immutable identity/version matches."""
     if status not in VALID_STATUSES:
         raise ValueError(f"Invalid status: {status}")
     binding_inferred = worker_session_id is None and status == "in_progress"
     worker_session_id = _infer_task_worker_session(
         identity, status=status, worker_session_id=worker_session_id,
     )
@@ -1727,16 +1827,25 @@ def api_update_task_if_current(
                     "ok": False,
                     "task_id": task_id,
                     "error": (
                         "prevalidated task revision changed before status update: "
                         f"expected {identity['sync_revision']}, "
                         f"found {task['sync_revision']}"
                     ),
                 }
+            claim_error = _task_claim_precondition_error(
+                conn,
+                task,
+                expected_status=expected_status,
+                require_unreserved=require_unreserved,
+            )
+            if claim_error:
+                conn.rollback()
+                return {"ok": False, "task_id": task_id, "error": claim_error}
             if binding_inferred and worker_session_id:
                 _validate_inferred_task_worker(conn, task, worker_session_id)
             result = update_task(
                 conn,
                 task_id,
                 status=status,
                 worker_session_id=worker_session_id,
             )
@@ -2943,40 +3052,53 @@ def api_update_task(par: str, title: str | None = None,
 
 
 def _api_update_task_if_current_unlocked(
     identity: TaskIdentity,
     *,
     status: str,
     worker_session_id: str | None = None,
     _canonical_first: bool = False,
+    expected_status: str = "",
+    require_unreserved: bool = False,
 ) -> dict:
     binding_inferred = worker_session_id is None and status == "in_progress"
     worker_session_id = _infer_task_worker_session(
         identity, status=status, worker_session_id=worker_session_id,
     )
     if binding_inferred and worker_session_id:
         with _conn() as conn:
             conn.execute("BEGIN IMMEDIATE")
             task = get_task_by_id(conn, identity["id"])
             if not task:
                 conn.rollback()
                 return {
                     "ok": False,
                     "task_id": identity["id"],
                     "error": "prevalidated task no longer exists",
                 }
+            claim_error = _task_claim_precondition_error(
+                conn,
+                task,
+                expected_status=expected_status,
+                require_unreserved=require_unreserved,
+            )
+            if claim_error:
+                conn.rollback()
+                return {"ok": False, "task_id": identity["id"], "error": claim_error}
             _validate_inferred_task_worker(conn, task, worker_session_id)
             conn.commit()
     context = _ia_context()
     if context is None:
         return _legacy_api_update_task_if_current(
             identity,
             status=status,
             worker_session_id=worker_session_id,
+            expected_status=expected_status,
+            require_unreserved=require_unreserved,
         )
     store = context.store
     assert store is not None
     try:
         detail = store.task_get(
             str(identity["par_number"]),
             project=identity["project_id"],
         )
@@ -2988,16 +3110,33 @@ def _api_update_task_if_current_unlocked(
     candidate_identity = _merge_canonical_task_identity(identity, detail)
     # У каждого хранилища СВОЙ счётчик ревизий: legacy двигают привязки воркеров
     # (`bind_task_to_session`, requeue, финализация), canonical их не видит. Прогонять
     # legacy-ревизию через canonical CAS — сравнение разных величин: любая задача, которую
     # хоть раз привязывали, отказывается навсегда.
     candidate_identity["sync_revision"] = int(
         detail.get("sync_revision", candidate_identity["sync_revision"])
     )
+    if expected_status and detail.get("status") != expected_status:
+        return {
+            "ok": False,
+            "error": (
+                f"promotion target must be {expected_status} "
+                f"(canonical found {detail.get('status')})"
+            ),
+            "ia_mode": context.mode,
+            "projection_debt": {},
+        }
+    if expected_status and detail.get("worker_session_id"):
+        return {
+            "ok": False,
+            "error": "canonical promotion target is already owned",
+            "ia_mode": context.mode,
+            "projection_debt": {},
+        }
     if context.mode == "shadow":
         if _canonical_first:
             try:
                 candidate = store.task_update_if_current(
                     candidate_identity,
                     status=status,
                     worker_session_id=worker_session_id,
                 )
@@ -3009,27 +3148,31 @@ def _api_update_task_if_current_unlocked(
                     "ia_mode": context.mode,
                     "shadow_match": False,
                     "projection_debt": _candidate_rejection_debt(candidate),
                 }
             legacy = _legacy_api_update_task_if_current(
                 identity,
                 status=status,
                 worker_session_id=worker_session_id,
+                expected_status=expected_status,
+                require_unreserved=require_unreserved,
             )
             return _shadow_result(
                 legacy,
                 candidate,
                 context,
                 ("ok", "par", "updated", "new_status", "sync_revision"),
             )
         legacy = _legacy_api_update_task_if_current(
             identity,
             status=status,
             worker_session_id=worker_session_id,
+            expected_status=expected_status,
+            require_unreserved=require_unreserved,
         )
         if not legacy.get("ok"):
             return legacy
         try:
             candidate = store.task_update_if_current(
                 candidate_identity,
                 status=status,
                 worker_session_id=worker_session_id,
@@ -3061,16 +3204,18 @@ def _api_update_task_if_current_unlocked(
             **candidate,
             "ia_mode": context.mode,
             "projection_debt": _candidate_rejection_debt(candidate),
         }
     legacy = _legacy_api_update_task_if_current(
         identity,
         status=status,
         worker_session_id=worker_session_id,
+        expected_status=expected_status,
+        require_unreserved=require_unreserved,
     )
     # Legacy-CAS — единственный оставшийся детектор устаревшей ревизии, и его отказ обязан
     # дойти до вызывающего отказом: иначе canonical переведён в in_progress с привязкой, а
     # `tm_tasks` остался `new`/NULL — то невозможное состояние, на котором гейт мержа
     # отказывает навсегда («task 'N' is not bound to session»).
     if not legacy.get("ok"):
         return {
             **legacy,
@@ -3090,23 +3235,27 @@ def _api_update_task_if_current_unlocked(
 
 
 def api_update_task_if_current(
     identity: TaskIdentity,
     *,
     status: str,
     worker_session_id: str | None = None,
     _canonical_first: bool = False,
+    expected_status: str = "",
+    require_unreserved: bool = False,
 ) -> dict:
     with _TASK_BINDING_LOCK:
         return _api_update_task_if_current_unlocked(
             identity,
             status=status,
             worker_session_id=worker_session_id,
             _canonical_first=_canonical_first,
+            expected_status=expected_status,
+            require_unreserved=require_unreserved,
         )
 
 
 def api_list_tasks(project: str = "", status: str = "",
                    assignee: str = "") -> dict:
     context = _ia_context()
     if context is None:
         return _legacy_api_list_tasks(project, status, assignee)
diff --git a/app/workspace.py b/app/workspace.py
index c9f479d59..eed112d5f 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -2045,16 +2045,223 @@ def branch_content_status(worktree_path: str, base_ref: str) -> dict:
         }
     except subprocess.TimeoutExpired as e:
         command = " ".join(str(part) for part in e.cmd)
         return {"error": f"{command} timed out"}
     except OSError as e:
         return {"error": f"git content check failed: {type(e).__name__}: {e}"}
 
 
+def promote_worktree_branch(
+    worktree_path: str,
+    new_branch: str,
+    *,
+    from_ref: str,
+    expected_branch: str,
+    expected_head: str,
+) -> dict:
+    """Rename taskless adhoc work without moving its committed HEAD."""
+    wt = Path(worktree_path).resolve()
+    repo = _resolve_repo(str(wt), str(wt))
+    with repo_mutation_lock(repo):
+        from_ref = resolve_base_branch(str(repo), from_ref)
+        worker_name = new_branch.rsplit("/", 1)[-1]
+        if (
+            not expected_branch.startswith("adhoc-")
+            or expected_branch.rsplit("/", 1)[-1] != worker_name
+        ):
+            return {
+                "ok": False,
+                "state": "not_taskless_adhoc",
+                "error": f"branch '{expected_branch}' is not an adhoc branch for {worker_name}",
+            }
+        valid = _git_cmd(
+            ["git", "check-ref-format", "--branch", new_branch],
+            cwd=str(repo), capture_output=True, text=True,
+        )
+        if valid.returncode != 0:
+            return {
+                "ok": False,
+                "state": "invalid_target_branch",
+                "error": f"invalid branch '{new_branch}': {valid.stderr.strip()}",
+            }
+        status = _git_cmd(
+            ["git", "status", "--porcelain"], cwd=str(wt),
+            capture_output=True, text=True,
+        )
+        if status.returncode != 0:
+            detail = status.stderr.strip() or status.stdout.strip()
+            return {"ok": False, "state": "git_status_failed", "error": detail}
+        if status.stdout.strip():
+            return {
+                "ok": False,
+                "state": "dirty_worktree",
+                "error": "dirty working tree — commit or discard first",
+            }
+        try:
+            actual_branch, actual_head = inspect_worktree_identity(str(wt))
+        except RuntimeError as error:
+            return {"ok": False, "state": "identity_unavailable", "error": str(error)}
+        if actual_branch != expected_branch or actual_head != expected_head:
+            return {
+                "ok": False,
+                "state": "identity_changed",
+                "error": (
+                    f"worker identity changed: expected {expected_branch}@{expected_head}, "
+                    f"found {actual_branch}@{actual_head}"
+                ),
+                "branch": actual_branch,
+                "head": actual_head,
+            }
+        try:
+            target_head = _inspect_branch_ref(repo, new_branch)
+        except RuntimeError as error:
+            return {"ok": False, "state": "target_inspection_failed", "error": str(error)}
+        if target_head is not None:
+            return {
+                "ok": False,
+                "state": "target_branch_exists",
+                "error": f"branch '{new_branch}' already exists at {target_head}",
+                "branch": expected_branch,
+                "head": expected_head,
+            }
+        content = branch_content_status(str(wt), from_ref)
+        if content.get("error"):
+            return {
+                "ok": False,
+                "state": "content_check_failed",
+                "error": str(content["error"]),
+                "branch": expected_branch,
+                "head": expected_head,
+            }
+        if content.get("commits_ahead", 0) <= 0 or content.get("content_merged"):
+            return {
+                "ok": False,
+                "state": "no_unmerged_work",
+                "error": "current adhoc branch has no unmerged committed work to promote",
+                "branch": expected_branch,
+                "head": expected_head,
+                "commits_ahead": content.get("commits_ahead", 0),
+                "reason": content.get("reason", ""),
+            }
+        renamed = _git_cmd(
+            ["git", "branch", "-m", new_branch], cwd=str(wt),
+            capture_output=True, text=True,
+        )
+        if renamed.returncode != 0:
+            detail = renamed.stderr.strip() or renamed.stdout.strip()
+            return {
+                "ok": False,
+                "state": "promotion_failed",
+                "error": f"branch promotion failed: {detail}",
+                "branch": expected_branch,
+                "head": expected_head,
+            }
+        try:
+            promoted_branch, promoted_head = inspect_worktree_identity(str(wt))
+            old_head = _inspect_branch_ref(repo, expected_branch)
+            new_head = _inspect_branch_ref(repo, new_branch)
+        except RuntimeError as error:
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": f"branch promoted but verification failed: {error}",
+                "branch": new_branch,
+                "head": expected_head,
+            }
+        if (
+            promoted_branch != new_branch
+            or promoted_head != expected_head
+            or new_head != expected_head
+            or old_head is not None
+        ):
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": "branch promotion verification failed; promoted ref was preserved",
+                "branch": promoted_branch,
+                "head": promoted_head,
+            }
+        return {
+            "ok": True,
+            "state": "promoted_current_work",
+            "previous_branch": expected_branch,
+            "branch": new_branch,
+            "head": expected_head,
+            "commits_ahead": content["commits_ahead"],
+            "reason": content["reason"],
+        }
+
+
+def rollback_promoted_worktree_branch(
+    worktree_path: str,
+    *,
+    promoted_branch: str,
+    previous_branch: str,
+    expected_head: str,
+) -> dict:
+    """Undo only a promotion whose checked-out ref still owns the pinned HEAD."""
+    wt = Path(worktree_path).resolve()
+    repo = _resolve_repo(str(wt), str(wt))
+    with repo_mutation_lock(repo):
+        try:
+            actual_branch, actual_head = inspect_worktree_identity(str(wt))
+            previous_head = _inspect_branch_ref(repo, previous_branch)
+        except RuntimeError as error:
+            return {"ok": False, "state": "rollback_failed", "error": str(error)}
+        if actual_branch == previous_branch and actual_head == expected_head:
+            return {"ok": True, "state": "already_rolled_back", "branch": previous_branch,
+                    "head": expected_head}
+        if (
+            actual_branch != promoted_branch
+            or actual_head != expected_head
+            or previous_head is not None
+        ):
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": "promotion ownership changed; preserving all refs",
+                "branch": actual_branch,
+                "head": actual_head,
+            }
+        renamed = _git_cmd(
+            ["git", "branch", "-m", previous_branch], cwd=str(wt),
+            capture_output=True, text=True,
+        )
+        if renamed.returncode != 0:
+            detail = renamed.stderr.strip() or renamed.stdout.strip()
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": f"promotion rollback failed: {detail}",
+                "branch": promoted_branch,
+                "head": expected_head,
+            }
+        try:
+            actual_branch, actual_head = inspect_worktree_identity(str(wt))
+        except RuntimeError as error:
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": f"promotion rollback verification failed: {error}",
+                "branch": previous_branch,
+                "head": expected_head,
+            }
+        if actual_branch != previous_branch or actual_head != expected_head:
+            return {
+                "ok": False,
+                "state": "rollback_failed",
+                "error": "promotion rollback verification failed; current ref was preserved",
+                "branch": actual_branch,
+                "head": actual_head,
+            }
+        return {"ok": True, "state": "rolled_back", "branch": previous_branch,
+                "head": expected_head}
+
+
 def switch_worktree_branch(worktree_path: str, new_branch: str,
                            from_ref: str = "",
                            force: bool = False,
                            expect_absent: bool = False,
                            recreate_from_base: bool = False) -> dict:
     """expect_absent=True — вызывающий создаёт ЗАВЕДОМО новую ветку (авто-switch перед
     доставкой). Тогда существующая ветка того же имени — отказ, а не переиспользование:
     усыновление чужой истории должно быть невозможно, а не маловероятно (#27, E2).
diff --git a/tests/test_manager.py b/tests/test_manager.py
index c74d30459..57bb4857d 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -51,32 +51,26 @@ def _isolate_pipelines_dir(monkeypatch):
     pl.load_pipeline.cache_clear()
 
 
 class TestCreateSession:
     @pytest.mark.asyncio
     async def test_planned_initial_turn_is_refused_before_session_publish(
         self, mgr, monkeypatch,
     ):
-        from app.quota_gate import QuotaGateError, evaluate_worker_admission
+        from app.quota_gate import QuotaDecision, QuotaGateError
 
         async def blocked(_model, observation_loader=None):
             now = datetime.now(timezone.utc).timestamp()
-            # Середина недельного окна: линия 55.5%, факт 95% — выше неё.
-            reset_at = datetime.fromtimestamp(
-                now + 10080 * 60 / 2, timezone.utc,
-            ).isoformat()
-            return evaluate_worker_admission(
-                "claude-sonnet-5[1m]",
-                {"anthropic": {"label": "Claude", "windows": [{
-                    "id": "seven_day", "window_minutes": 10080,
-                    "utilization": 95, "resets_at": reset_at,
-                }]}},
-                {"anthropic": now},
-                now=now,
+            return QuotaDecision(
+                state="blocked", model="claude-sonnet-5[1m]",
+                provider="anthropic", provider_label="Claude", lane="claude",
+                gated=True, utilization=95, progress=0.5, tolerance_pp=5.5,
+                limit_pct=55.5, observed_at=now, valid_until=now + 60,
+                reset_at=None, window_starts_at=None, reason="test refusal",
             )
 
         monkeypatch.setattr("app.quota_gate.get_worker_admission", blocked)
         with pytest.raises(QuotaGateError):
             await mgr.create_session(
                 name="blocked-worker", scope="/s", cwd="/tmp",
                 model="claude-sonnet-5[1m]", planned_initial_turn=True,
             )
diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index 3d67820df..09704a0d9 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -1935,16 +1935,41 @@ async def test_switch_worker_branch_forwards_explicit_force(monkeypatch):
         return {"ok": True, "branch": "task-91/coder"}
 
     with patch.object(m, "_api", side_effect=fake_api):
         await m.switch_worker_branch(name="coder", task_id="91", force=True)
 
     assert captured["force"] is True
 
 
+@pytest.mark.asyncio
+async def test_t2_switch_worker_branch_forwards_explicit_promotion(monkeypatch):
+    import app.mcp_stdio as m
+
+    monkeypatch.setattr(m, "SCOPE", "/s")
+    captured = {}
+
+    async def fake_api(_method, _path, **kwargs):
+        captured.update(kwargs["json"])
+        return {
+            "ok": True,
+            "state": "promoted_current_work",
+            "branch": "task-91/coder",
+        }
+
+    assert "promote_current" in inspect.signature(m.switch_worker_branch).parameters
+    with patch.object(m, "_api", side_effect=fake_api):
+        output = await m.switch_worker_branch(
+            name="coder", task_id="91", promote_current=True,
+        )
+
+    assert captured["promote_current"] is True
+    assert output == "Promoted current work to branch task-91/coder"
+
+
 @pytest.mark.asyncio
 async def test_switch_worker_branch_forwards_owned_dirs_json(monkeypatch):
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     captured = {}
 
     async def fake_api(_method, _path, **kwargs):
         captured.update(kwargs["json"])
diff --git a/tests/test_task_tracker_integration.py b/tests/test_task_tracker_integration.py
index fae94c67b..a6e0f2ce1 100644
--- a/tests/test_task_tracker_integration.py
+++ b/tests/test_task_tracker_integration.py
@@ -306,16 +306,54 @@ def _commit_file(worktree_path: str, filename: str, message: str) -> str:
         ["git", "commit", "-m", message], cwd=path, check=True, capture_output=True,
     )
     return subprocess.run(
         ["git", "rev-parse", "HEAD"], cwd=path,
         check=True, capture_output=True, text=True,
     ).stdout.strip()
 
 
+def _make_taskless_adhoc_worker(
+    monkeypatch, tmp_path: Path, *, name: str, target_status: str = "new",
+):
+    import app.workspace as workspace
+    from app import tm
+
+    _init_db()
+    repo = _make_git_scope(monkeypatch, tmp_path)
+    scope = str(repo)
+    with tm._conn() as connection:
+        tm.ensure_project(connection, "project", scope=scope)
+        tm.create_task(
+            connection, "project", "Already completed", par_number=42, status="done",
+        )
+        target = tm.create_task(
+            connection, "project", "Adopt current work", par_number=43,
+            status=target_status,
+        )
+    worktree = workspace.create_worktree(scope, name)
+    adhoc_branch = f"adhoc-1800000000-1/{name}"
+    subprocess.run(
+        ["git", "branch", "-m", adhoc_branch],
+        cwd=worktree.path, check=True, capture_output=True,
+    )
+    worker_head = _commit_file(
+        worktree.path, "adhoc.txt", "#43: preserve current adhoc work",
+    )
+    _save_worker(
+        session_id=name,
+        task_id="",
+        scope=scope,
+        worktree_path=worktree.path,
+        branch=adhoc_branch,
+    )
+    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)
+    return repo, worktree, found, target, adhoc_branch, worker_head
+
+
 @pytest.mark.asyncio
 async def test_t2_bound_task_and_outcome_are_validated_before_git(monkeypatch):
     """Neither a made-up current task nor a missing disposition may reach Git."""
     import app.routes.sessions as sessions_route
     from app import tm
 
     _init_db()
     _seed_project()
@@ -710,16 +748,472 @@ async def test_t3_complete_merge_atomically_links_and_closes_current_task(monkey
     with tm._conn() as connection:
         closed = tm.get_task_by_id(connection, task["id"])
     assert closed["status"] == "done"
     assert closed["worker_session_id"] is None
     assert closed["completed_at"]
     assert "abc123" in closed["git_commits"]
 
 
+@pytest.mark.asyncio
+async def test_t1_normal_complete_persists_null_done_control(monkeypatch):
+    """A normal completed task stays done while its worker becomes deliberately taskless."""
+    import app.routes.sessions as sessions_route
+    from app import tm
+    from app.db import get_session
+
+    _init_db()
+    _seed_project()
+    with tm._conn() as connection:
+        task = tm.create_task(
+            connection, "project", "Normal completion", par_number=42,
+            status="in_progress",
+        )
+        connection.execute(
+            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
+            ("normal-complete-worker", task["id"]),
+        )
+    _save_worker(session_id="normal-complete-worker", task_id="42")
+    found = _prepare_merge(monkeypatch, session_id="normal-complete-worker")
+    monkeypatch.setattr(
+        "app.workspace.merge_worktree_to_main",
+        lambda *_args, **_kwargs: {
+            "ok": True,
+            "commits_merged": 1,
+            "branch": found.branch,
+            "merged_commits": {
+                "42": [{"hash": "done42", "message": "#42: complete normally"}],
+            },
+        },
+    )
+
+    result = await sessions_route.execute_merge_session(
+        session_id=found.id,
+        expected_name=found.name,
+        expected_scope=found.scope,
+        expected_branch=found.branch,
+        expected_head="d" * 40,
+        req={"scope": "/scope", "task_outcome": "complete", "merge_schema_version": 2},
+    )
+
+    assert result["ok"] is True
+    with tm._conn() as connection:
+        closed = tm.get_task_by_id(connection, task["id"])
+    durable = get_session(found.id)
+    assert (closed["status"], closed["worker_session_id"]) == ("done", None)
+    assert (durable["task_id"], durable["needs_switch"]) == ("", 1)
+
+
+@pytest.mark.asyncio
+async def test_t2_taskless_adhoc_deadlock_promotes_head_then_merge_succeeds(
+    monkeypatch, tmp_path,
+):
+    import app.routes.sessions as sessions_route
+    from app import tm
+    from app.db import get_session
+
+    repo, worktree, found, target, adhoc_branch, worker_head = (
+        _make_taskless_adhoc_worker(
+            monkeypatch, tmp_path, name="promote-worker",
+        )
+    )
+
+    refused_merge = await sessions_route.execute_merge_session(
+        session_id=found.id,
+        expected_name=found.name,


## LATER FIX e3d29ad1f8 (1.6 days later): #499: surface and repair derived lifecycle quarantine
lines of origin it changed/deleted: 14
(code only, capped 400 lines)

#499: surface and repair derived lifecycle quarantine

Orchestra-Operation: 84114906-fa94-4a33-92c7-b8d1f3a35e2e


diff --git a/app/ia/task_store.py b/app/ia/task_store.py
index ee379042c..4fabdc773 100644
--- a/app/ia/task_store.py
+++ b/app/ia/task_store.py
@@ -1468,22 +1468,25 @@ class TaskStore:
         *,
         status: str,
         worker_session_id: str | None = None,
     ) -> dict[str, Any]:
         if not isinstance(identity, Mapping):
             raise ValueError("task identity must be a mapping")
         project_id = str(identity.get("project_id") or "")
         display_number = int(identity.get("display_number") or identity.get("par_number") or 0)
+        # Snapshot the global CAS before validating this task. An unrelated earlier
+        # generation is harmless, but any generation committed after this point must
+        # make task_update() reject rather than letting a stale same-task caller adopt it.
+        expected_head = identity.get("canonical_head") or self.canonical_head
         state = self._find_state(str(display_number), project_id)
         if identity.get("stable_id") and identity["stable_id"] != state["stable_id"]:
             return {"ok": False, "error": "prevalidated task stable identity changed"}
         if int(identity.get("sync_revision", -1)) != int(state.get("sync_revision", 0)):
             return {"ok": False, "error": "prevalidated task revision changed"}
-        expected_head = identity.get("canonical_head") or state["canonical_head"]
         updated = self.task_update(
             str(display_number),
             project=project_id,
             status=status,
             worker_session_id=worker_session_id,
             expected_head=str(expected_head),
         )
         current = self._find_state(str(display_number), project_id)
diff --git a/app/manager.py b/app/manager.py
index cc1b507de..9ba94dbb6 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -100,16 +100,36 @@ class LockBusy(RuntimeError):
         self.what, self.worker, self.waited = what, worker, waited
         super().__init__(
             f"worker '{worker}' is busy: another operation has held the session lock for "
             f"{waited:.0f}s (message delivery or merge in flight). Nothing was changed — "
             f"retry {what} in ~30s."
         )
 
 
+class LifecycleQuarantineError(RuntimeError):
+    """A durable task/branch binding blocks delivery until an explicit repair."""
+
+    def __init__(self, lifecycle: dict):
+        self.lifecycle = lifecycle
+        super().__init__(str(lifecycle["message"]))
+
+    def envelope(self) -> dict:
+        return {
+            "code": self.lifecycle["code"],
+            "message": self.lifecycle["message"],
+            "retryable": False,
+            "outcome_unknown": False,
+            "details": {
+                "task_id": self.lifecycle["task_id"],
+                "repair": self.lifecycle["repair"],
+            },
+        }
+
+
 @asynccontextmanager
 async def wait_for_session_lock(lock, *, what: str, worker: str, limit: float | None = None):
     """Взять лок сессии так, чтобы ожидание было ВИДНО снаружи.
 
     Замер #27: доставка держит лок секундами (коннект CLI-бэкенда 1.6–2.0 с, а `connect()`
     внутри разрешает себе до 60 с), git при этом занимает 0.01 с. Раньше ожидание не
     оставляло ни строки в журнале и ни поля в ответе — снаружи оно было неотличимо от
     зависшего сервера.
@@ -1020,30 +1040,19 @@ class SessionManager:
             durable = await asyncio.to_thread(get_session, session.id)
             if durable:
                 session.branch = durable.get("branch") or session.branch
                 session.base_branch = durable.get("base_branch") or session.base_branch
                 session.task_id = durable.get("task_id") or ""
                 session.needs_switch = bool(durable.get("needs_switch") or 0)
         if not session.needs_switch:
             return
-        if str(session.task_id or ""):
-            from app.tm import task_binding_requires_quarantine
-
-            blocked = await asyncio.to_thread(
-                task_binding_requires_quarantine,
-                session.scope,
-                session.id,
-                str(session.task_id),
-            )
-            if blocked:
-                raise RuntimeError(
-                    f"worker lifecycle is quarantined for task #{session.task_id}; "
-                    "repair the task/branch binding before delivery"
-                )
+        lifecycle = await asyncio.to_thread(self.lifecycle_quarantine, session)
+        if lifecycle:
+            raise LifecycleQuarantineError(lifecycle)
         if session.status != AgentStatus.IDLE:
             raise RuntimeError(
                 f"worker is {session.status.value} — cannot auto-switch before delivery"
             )
         if not session.worktree_path:
             raise RuntimeError("auto-switch failed: session has no worktree")
 
         async with session._lifecycle_lock:
@@ -1242,18 +1251,58 @@ class SessionManager:
     async def preflight_message_delivery(self, session_id: str) -> None:
         """Run the target's new-turn gate before accepting a direct receipt."""
         session = self.sessions.get(session_id)
         if session is None:
             row = get_session(session_id)
             session = self._hydrate_row(row) if row else None
         if session is None:
             raise KeyError(f"session not found: {session_id}")
+        await self._auto_switch_before_delivery(session)
         await session.preflight_delivery_admission()
 
+    @staticmethod
+    def lifecycle_quarantine(session) -> dict:
+        """Project the delivery gate's derived quarantine state for every reader."""
+        get = session.get if isinstance(session, dict) else lambda key, default="": getattr(
+            session, key, default,
+        )
+        task_id = str(get("task_id", "") or "")
+        if not bool(get("needs_switch", False)) or not task_id:
+            return {}
+        from app.tm import task_binding_requires_quarantine
+
+        scope = str(get("scope", "") or "")
+        session_id = str(get("id", "") or "")
+        if not task_binding_requires_quarantine(scope, session_id, task_id):
+            return {}
+        name = str(get("name", "") or "")
+        base_branch = str(get("base_branch", "") or "main")
+        call = (
+            f'switch_worker_branch(name="{name}", task_id="{task_id}", '
+            f'from_ref="{base_branch}")'
+        )
+        return {
+            "code": "LIFECYCLE_QUARANTINED",
+            "task_id": task_id,
+            "repair": {
+                "tool": "switch_worker_branch",
+                "arguments": {
+                    "name": name,
+                    "task_id": task_id,
+                    "from_ref": base_branch,
+                },
+                "call": call,
+            },
+            "message": (
+                f"worker lifecycle is quarantined for task #{task_id}; repair with "
+                f"{call}. The call is idempotent when the binding is already healthy."
+            ),
+        }
+
     async def interrupt(self, session_id: str) -> None:
         session = self.sessions.get(session_id)
         if session:
             await session.interrupt()
 
     async def stop_worker(self, session_id: str) -> None:
         session = self.sessions.get(session_id)
         if session:
@@ -2321,16 +2370,20 @@ class SessionManager:
         for row in get_all_sessions(scope):
             if row["id"] not in seen:
                 result.append(row)
         # Cache-timer metadata is runtime-derived; Codex exposes only an approximate window.
         turn_map = get_last_turn_map()
         for r in result:
             r["last_turn_ts"] = turn_map.get(r["id"])
             r.update(cache_policy_for_runtime(runtime_for_record(r)))
+            lifecycle = self.lifecycle_quarantine(r)
+            if lifecycle:
+                r["status"] = "quarantined"
+                r["lifecycle_status"] = lifecycle
             for omit in self._LIST_OMIT:
                 r.pop(omit, None)
         return result
 
     def get_session_id(self, name: str, scope: str) -> str | None:
         for s in self.sessions.values():
             if s.name == name and s.scope == scope:
                 return s.id
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 6359d6b1c..dbbf2e2c5 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1798,17 +1798,25 @@ async def list_agents() -> str:
         cache = _cache_pill(s)
         cache_str = f" | {cache}" if cache else ""
         task = s.get('task_id', '')
         task_str = f" | {task}" if task else ""
         desc = s.get('description', '')
         desc_str = f' | "{desc}"' if desc else ""
         owner = s.get('parent_name', '')
         owner_str = f" | owner: {owner}" if show_owner and owner else ""
-        return f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{cache_str}{task_str}{desc_str}{owner_str}"
+        lifecycle = s.get("lifecycle_status")
+        lifecycle_str = ""
+        if isinstance(lifecycle, dict):
+            repair = lifecycle.get("repair") or {}
+            lifecycle_str = (
+                f" | {lifecycle.get('code', 'LIFECYCLE_BLOCKED')}: "
+                f"{repair.get('call', lifecycle.get('message', 'repair required'))}"
+            )
+        return f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{cache_str}{task_str}{desc_str}{owner_str}{lifecycle_str}"
 
     is_worker = ROLE not in _ORCH_ROLES
     orchestrators, my_workers, other_workers = [], [], []
     for s in sessions:
         if s.get("role", "worker") in _ORCH_ROLES:
             if is_worker and PARENT_NAME and s["name"] != PARENT_NAME:
                 continue
             orchestrators.append(s)
@@ -2812,16 +2820,30 @@ async def switch_worker_branch(
     if isinstance(result, dict) and result.get("error"):
         return f"Switch failed: {result['error']}"
     if (
         isinstance(result, dict)
         and result.get("ok")
         and result.get("state") == "promoted_current_work"
     ):
         return f"Promoted current work to branch {result.get('branch', '?')}"
+    if (
+        isinstance(result, dict)
+        and result.get("ok")
+        and result.get("state") == "lifecycle_repaired"
+    ):
+        return f"Repaired lifecycle binding on branch {result.get('branch', '?')}"
+    if (
+        isinstance(result, dict)
+        and result.get("ok")
+        and result.get("state") == "already_current"
+    ):
+        return (
+            f"No-op: worker is already on healthy branch {result.get('branch', '?')}"
+        )
     if isinstance(result, dict) and result.get("ok"):
         return f"Switched to branch {result.get('branch', '?')}"
     if isinstance(result, dict) and result.get("conflicts"):
         return f"Merge conflict with base branch on: {', '.join(result['conflicts'])}"
     return f"Switch result: {result}"
 
 
 @mcp.tool()
@@ -2850,21 +2872,30 @@ async def worker_wip(name: str, base_ref: str = "") -> str:
         return f"WIP check failed: {result['error']}"
     if not isinstance(result, dict):
         return f"WIP result: {result}"
     uncommitted = result.get("uncommitted", [])
     unmerged = result.get("unmerged_commits", [])
     changed_files = result.get("changed_files", [])
     ctx = result.get("context_pct", 0)
     status = result.get("status", "?")
+    lifecycle = result.get("lifecycle_status")
+    lifecycle_line = ""
+    if isinstance(lifecycle, dict):
+        repair = lifecycle.get("repair") or {}
+        lifecycle_line = (
+            f"QUARANTINED {lifecycle.get('code', 'LIFECYCLE_BLOCKED')}: "
+            f"{lifecycle.get('message', '')}\n"
+            f"Repair: {repair.get('call', '')}\n"
+        )
     effective_base = result.get("base_ref") or base_ref or "persisted base"
     ctx_str = f" | ctx:{ctx}% | {status}" if ctx else f" | {status}"
     if not uncommitted and not unmerged:
-        return f"'{name}'{ctx_str}: clean — no uncommitted changes, no unmerged commits (vs {effective_base})"
-    parts = [f"WIP for '{name}'{ctx_str} (vs {effective_base}):"]
+        return lifecycle_line + f"'{name}'{ctx_str}: clean — no uncommitted changes, no unmerged commits (vs {effective_base})"
+    parts = [lifecycle_line + f"WIP for '{name}'{ctx_str} (vs {effective_base}):"]
     if uncommitted:
         parts.append(f"  Uncommitted ({len(uncommitted)}): " + ", ".join(uncommitted[:20]))
     if unmerged:
         parts.append(f"  Unmerged commits ({len(unmerged)}):")
         parts.extend(f"    - {s}" for s in unmerged[:20])
     if changed_files:
         insertions = result.get("insertions", 0)
         deletions = result.get("deletions", 0)
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 7943bba19..93a71b2d0 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -26,16 +26,17 @@ from app.db import (
     get_runtime_handoff,
     get_session as get_session_row,
     get_session_by_name,
 )
 from app.deps import manager
 from app.errtext import err_text
 from app.events import MessageProvenance
 from app.models import ensure_dashboard_visible, ensure_spawn_allowed, resolve_model, MODELS
+from app.manager import LifecycleQuarantineError
 from app.quota_gate import QuotaGateError
 from app.routes.errors import keyed_auth_required
 from app.session import AgentStatus
 from app.session_state import empty_context
 from app.status_policy import is_internal_telemetry_status
 from app.user_message_display import add_user_message_time_prefix, annotate_user_message
 
 logger = logging.getLogger("orchestra.sessions")
@@ -783,35 +784,59 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
             existing = message_deliveries._row(delivery_id)
             if existing is not None:
                 if not operator and existing["source_session_id"] != source_id:
                     return keyed_auth_required()
                 if name != existing["target_name"]:
                     conflict, conflict_status = message_deliveries._conflict(delivery_id)
                     return JSONResponse(conflict, status_code=conflict_status)
                 if existing["state"] == "FAILED_BEFORE_SUBMIT":
-                    await manager.preflight_message_delivery(existing["target_session_id"])
-                resource, status_code = await message_deliveries.accept_message_delivery(
-                    delivery_id=delivery_id,
-                    source_session_id=source_id or None,
-                    source_principal=source_principal,
-                    source_name=source_name,
-                    source_scope=source_scope,
-                    source_task_id=source_task_id,
-                    target_session_id=existing["target_session_id"],
-                    target_name=existing["target_name"],
-                    target_scope=existing["target_scope"],
-                    target_task_id=existing["target_task_id"],
-                    target_generation=existing["target_generation"],
-                    message=req.message,
-                    rendered_message=rendered,
-                    message_kind=req.message_kind,
-                    wake=req.wake,
-                    provenance=provenance,
-                )
+                    async with manager.get_session_lock(existing["target_session_id"]):
+                        await manager.preflight_message_delivery(
+                            existing["target_session_id"],
+                        )
+                        resource, status_code = (
+                            await message_deliveries.accept_message_delivery(
+                                delivery_id=delivery_id,
+                                source_session_id=source_id or None,
+                                source_principal=source_principal,
+                                source_name=source_name,
+                                source_scope=source_scope,
+                                source_task_id=source_task_id,
+                                target_session_id=existing["target_session_id"],
+                                target_name=existing["target_name"],
+                                target_scope=existing["target_scope"],
+                                target_task_id=existing["target_task_id"],
+                                target_generation=existing["target_generation"],
+                                message=req.message,
+                                rendered_message=rendered,
+                                message_kind=req.message_kind,
+                                wake=req.wake,
+                                provenance=provenance,
+                            )
+                        )
+                else:
+                    resource, status_code = await message_deliveries.accept_message_delivery(
+                        delivery_id=delivery_id,
+                        source_session_id=source_id or None,
+                        source_principal=source_principal,
+                        source_name=source_name,
+                        source_scope=source_scope,
+                        source_task_id=source_task_id,
+                        target_session_id=existing["target_session_id"],
+                        target_name=existing["target_name"],
+                        target_scope=existing["target_scope"],
+                        target_task_id=existing["target_task_id"],
+                        target_generation=existing["target_generation"],
+                        message=req.message,
+                        rendered_message=rendered,
+                        message_kind=req.message_kind,
+                        wake=req.wake,
+                        provenance=provenance,
+                    )
                 return JSONResponse(resource, status_code=status_code)
 
             known_targets = get_all_sessions(include_archived=True)
             exact_archived = any(
                 row["name"] == name
                 and row["scope"].rstrip("/") == req.scope.rstrip("/")
                 and row["status"] == "archived"
                 for row in known_targets
@@ -864,40 +889,41 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                         "error": {
                             "code": "TARGET_NOT_FOUND",
                             "message": f"agent '{name}' not found",
                             "outcome_unknown": False,
                         }
                     },
                     status_code=404,
                 )
-            await manager.preflight_message_delivery(target.id)
-            target_generation = (
-                f"session={target.id}|task={getattr(target, 'task_id', '')}|"
-                f"branch={getattr(target, 'branch', '')}|"