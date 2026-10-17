# Candidate cand-43

## ORIGIN commit ecd683e5ca (2026-08-26): Merge remote-tracking branch 'origin/main'
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/manager.py b/app/manager.py
index 6ce46c9d6..4472a27d2 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1147,16 +1147,26 @@ class SessionManager:
                     )
                 await self._auto_switch_before_delivery(session)
                 await session.send(message, delivery=delivery)
 
         delivery_task = asyncio.create_task(deliver())
         await _wait_owned_task(delivery_task)
         delivery_task.result()
 
+    async def preflight_message_delivery(self, session_id: str) -> None:
+        """Run the target's new-turn gate before accepting a direct receipt."""
+        session = self.sessions.get(session_id)
+        if session is None:
+            row = get_session(session_id)
+            session = self._hydrate_row(row) if row else None
+        if session is None:
+            raise KeyError(f"session not found: {session_id}")
+        await session.preflight_delivery_admission()
+
     async def interrupt(self, session_id: str) -> None:
         session = self.sessions.get(session_id)
         if session:
             await session.interrupt()
 
     async def stop_worker(self, session_id: str) -> None:
         session = self.sessions.get(session_id)
         if session:
diff --git a/app/message_deliveries.py b/app/message_deliveries.py
index 7cfb2c173..baeb94b19 100644
--- a/app/message_deliveries.py
+++ b/app/message_deliveries.py
@@ -254,30 +254,39 @@ def prepare_message_delivery(delivery_id: str) -> dict:
         return {
             **_resource(row),
             "user_log_id": row["user_log_id"],
             "history_user_message": user_log["content"] if user_log else row["rendered_message"],
         }
 
 
 def _update_state(delivery_id: str, state: str, *, provider_ref: str | None = None,
-                  error: dict | None = None) -> dict:
+                  error: dict | None = None, clear_user_log: bool = False) -> dict:
     with db._conn() as connection:
         connection.execute("BEGIN IMMEDIATE")
         row = connection.execute(
             "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
         ).fetchone()
         if row is None:
             raise KeyError(f"message delivery not found: {delivery_id}")
         values = (provider_ref, json.dumps(error, ensure_ascii=False) if error else None,
                   _now(), delivery_id)
         connection.execute(
             "UPDATE message_deliveries SET state=?, provider_ref=?, error_json=?, updated_at=? WHERE delivery_id=?",
             (state, *values),
         )
+        if clear_user_log and row["user_log_id"] is not None:
+            connection.execute(
+                "DELETE FROM logs WHERE id=? AND session_id=? AND type='user_message'",
+                (row["user_log_id"], row["target_session_id"]),
+            )
+            connection.execute(
+                "UPDATE message_deliveries SET user_log_id=NULL WHERE delivery_id=?",
+                (delivery_id,),
+            )
         row = connection.execute(
             "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
         ).fetchone()
         return _resource(row)
 
 
 def mark_message_delivery_dispatching(delivery_id: str) -> dict:
     row = _row(_validate_id(delivery_id))
@@ -307,17 +316,26 @@ def _failure(error: BaseException) -> dict:
         "code": "DELIVERY_NOT_SUBMITTED",
         "message": f"Provider submission did not begin: {err_text(error)}",
         "retryable": True,
         "outcome_unknown": False,
     }
 
 
 def mark_message_delivery_failed_before_submit(delivery_id: str, error: BaseException) -> dict:
-    return _update_state(delivery_id, "FAILED_BEFORE_SUBMIT", error=_failure(error))
+    from app.quota_gate import QuotaGateError
+
+    # A quota refusal is known before any provider work; retaining its prepared
+    # user-log would make the dashboard claim that a turn was delivered.
+    return _update_state(
+        delivery_id,
+        "FAILED_BEFORE_SUBMIT",
+        error=_failure(error),
+        clear_user_log=isinstance(error, QuotaGateError),
+    )
 
 
 def mark_message_delivery_unknown(delivery_id: str, error: BaseException, *, orphaned: bool = False) -> dict:
     error_json = json.dumps(
         {
             "code": "DELIVERY_OUTCOME_UNKNOWN",
             "message": (
                 "Server restarted while provider acceptance was in flight; delivery may "
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 19c24fa0e..ff08e81e9 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -726,16 +726,18 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                                 "outcome_unknown": False,
                             }
                         },
                         status_code=403,
                     )
                 if name != existing["target_name"]:
                     conflict, conflict_status = message_deliveries._conflict(delivery_id)
                     return JSONResponse(conflict, status_code=conflict_status)
+                if existing["state"] == "FAILED_BEFORE_SUBMIT":
+                    await manager.preflight_message_delivery(existing["target_session_id"])
                 resource, status_code = await message_deliveries.accept_message_delivery(
                     delivery_id=delivery_id,
                     source_session_id=source_id or None,
                     source_principal=source_principal,
                     source_name=source_name,
                     source_scope=source_scope,
                     source_task_id=source_task_id,
                     target_session_id=existing["target_session_id"],
@@ -812,16 +814,17 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                         "error": {
                             "code": "TARGET_NOT_FOUND",
                             "message": f"agent '{name}' not found",
                             "outcome_unknown": False,
                         }
                     },
                     status_code=404,
                 )
+            await manager.preflight_message_delivery(target.id)
             target_generation = (
                 f"session={target.id}|task={getattr(target, 'task_id', '')}|"
                 f"branch={getattr(target, 'branch', '')}|"
                 f"needs_switch={int(bool(getattr(target, 'needs_switch', False)))}"
             )
             resource, status_code = await message_deliveries.accept_message_delivery(
                 delivery_id=delivery_id,
                 source_session_id=source_id or None,
diff --git a/app/session.py b/app/session.py
index af438fb61..f763b234b 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1035,16 +1035,59 @@ class AgentSession:
 
     async def _worker_admission(self, model: str) -> "QuotaDecision":
         if self._admission_service is not None:
             return await self._admission_service(model)
         from app.quota_gate import get_worker_admission
 
         return await get_worker_admission(model)
 
+    async def preflight_delivery_admission(self) -> None:
+        """Check a new direct delivery before its durable receipt is accepted."""
+        decision = None
+        admitted_model = ""
+        admitted_stop_gen = -1
+        while True:
+            await self._lifecycle_lock.acquire()
+            if self._handoff_recovery_required:
+                self._lifecycle_lock.release()
+                raise RuntimeError(
+                    "handoff_recovery_required: operator recovery is required before sends"
+                )
+            # Direct delivery can be injected into an existing turn.  In that case
+            # the normal send path intentionally does not consume a new-turn quota.
+            if self._compacting or self.status == AgentStatus.RUNNING or self.is_orchestrator:
+                self._lifecycle_lock.release()
+                return
+            if decision is None:
+                admitted_model = self.model
+                admitted_stop_gen = self._turn_start_cancel_gen
+                self._lifecycle_lock.release()
+                decision = await self._worker_admission(admitted_model)
+                continue
+            if admitted_stop_gen != self._turn_start_cancel_gen or self.model != admitted_model:
+                decision = None
+                self._lifecycle_lock.release()
+                continue
+            if (
+                decision.state in {"available", "blocked"}
+                and decision.valid_until is not None
+                and time.time() >= decision.valid_until
+            ):
+                decision = None
+                self._lifecycle_lock.release()
+                continue
+            try:
+                from app.quota_gate import require_worker_admission
+
+                require_worker_admission(decision)
+            finally:
+                self._lifecycle_lock.release()
+            return
+
     async def send(self, message: str | InjectedMessage, *, delivery=None) -> None:
         message_event_id = message.event_id if isinstance(message, InjectedMessage) else ""
         message = message.text if isinstance(message, InjectedMessage) else message
         original_user_message = message
         history_user_message = original_user_message
         if delivery is not None:
             persisted_user_message = getattr(delivery, "history_user_message", None)
             if isinstance(persisted_user_message, str) and persisted_user_message:
diff --git a/tests/test_delivery_head_of_line_block.py b/tests/test_delivery_head_of_line_block.py
index 0455c5d79..90f742d2d 100644
--- a/tests/test_delivery_head_of_line_block.py
+++ b/tests/test_delivery_head_of_line_block.py
@@ -99,16 +99,40 @@ def test_delivery_unknown_still_blocks_on_purpose(tmp_path, patched_conn):
     patched_conn(connection)
 
     head = message_deliveries._next_target_delivery("sess")
 
     assert head["delivery_id"] == "ambiguous"
     assert "DELIVERY_UNKNOWN" not in message_deliveries._TERMINAL_DELIVERY_STATES
 
 
+@pytest.mark.asyncio
+async def test_delivery_unknown_head_does_not_send_later_message(tmp_path, patched_conn):
+    connection = _make_db(
+        tmp_path,
+        [
+            (1, "ambiguous", "sess", "DELIVERY_UNKNOWN"),
+            (2, "later", "sess", "QUEUED"),
+        ],
+    )
+    patched_conn(connection)
+    calls = []
+
+    class Manager:
+        async def send_message_delivery(self, *args, **kwargs):
+            calls.append((args, kwargs))
+
+    drained = await message_deliveries.run_target_message_deliveries(
+        "sess", manager=Manager(),
+    )
+
+    assert drained is False
+    assert calls == []
+
+
 def test_in_flight_states_are_not_skipped(tmp_path, patched_conn):
     """Обратное плечо: PREPARING/DISPATCHING — НЕ терминальные, их пропускать нельзя."""
     connection = _make_db(
         tmp_path,
         [
             (1, "busy", "sess", "DISPATCHING"),
             (2, "later", "sess", "QUEUED"),
         ],
diff --git a/tests/test_message_delivery_receipts_380.py b/tests/test_message_delivery_receipts_380.py
index 3f88bdcf7..ac1d4211a 100644
--- a/tests/test_message_delivery_receipts_380.py
+++ b/tests/test_message_delivery_receipts_380.py
@@ -895,16 +895,69 @@ def _request_with_proof(session_id, proof):
         headers={
             "x-orchestra-session-id": session_id,
             "x-orchestra-mcp-proof": proof,
         },
         cookies={},
     )
 
 
+@pytest.mark.asyncio
+async def test_t401_quota_refusal_is_returned_before_receipt_or_user_log(
+    message_db, monkeypatch,
+):
+    """A known quota refusal is visible to the MCP caller, not an accepted queue row."""
+    from app.quota_gate import evaluate_worker_admission
+    from app.mcp_proof import issue_mcp_proof
+    from app.routes import sessions as routes
+
+    target = routes.manager.get_by_name(TARGET_NAME, SCOPE)
+    assert target is not None
+    target.model = "claude-sonnet-5[1m]"
+    now = datetime.now(timezone.utc).timestamp()
+    reset_at = datetime.fromtimestamp(
+        now + 10080 * 60 / 2, timezone.utc,
+    ).isoformat()
+    blocked = evaluate_worker_admission(
+        target.model,
+        {"anthropic": {"label": "Claude", "windows": [{
+            "id": "seven_day",
+            "window_minutes": 10080,
+            "utilization": 95,
+            "resets_at": reset_at,
+        }]}},
+        {"anthropic": now},
+        now=now,
+    )
+    target._admission_service = AsyncMock(return_value=blocked)
+    monkeypatch.setitem(routes.manager.sessions, TARGET_ID, target)
+    request = _request_with_proof(SOURCE_ID, issue_mcp_proof(SOURCE_ID))
+    response = await routes.send_message(
+        TARGET_NAME,
+        routes.SendRequest(
+            delivery_id=DELIVERY_ID,
+            message=MESSAGE,
+            sender=SOURCE_NAME,
+            scope=SCOPE,
+        ),
+        request=request,
+    )
+
+    assert getattr(response, "status_code", None) == 429
+    payload = _response_payload(response)
+    error = payload["error"]
+    assert error["code"] == "weekly_quota_blocked"
+    assert "Claude" in error["message"]
+    assert "95%" in error["message"]
+    assert "line limit" in error["message"]
+    assert "55.5" in error["message"]
+    assert _delivery_row(message_db) is None
+    assert _user_messages(message_db) == []
+
+
 @pytest.mark.asyncio
 async def test_t380_r6_http_auth_conflict_rollback_and_name_ambiguity_are_known(
     message_db, monkeypatch,
 ):
     """Keyed REST derives identity from MCP proof and rejects every pre-accept spoof."""
     from app import db
     from app.mcp_proof import issue_mcp_proof
     from app.routes import sessions as routes


## LATER FIX e3d29ad1f8 (9.9 days later): #499: surface and repair derived lifecycle quarantine
lines of origin it changed/deleted: 2
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