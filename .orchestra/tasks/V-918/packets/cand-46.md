# Candidate cand-46

## ORIGIN commit 1750acf36d (2026-07-28): #91: #91: synchronize lifecycle operations with turn completion
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 6452b12c7..33e640e79 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1,16 +1,15 @@
 """Session routes: CRUD, send, stream, merge/switch, model/prompt/description management."""
 
 import asyncio
 import logging
 import re
 import sqlite3
 from contextlib import AsyncExitStack
-from math import ceil
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, Request
 from fastapi.responses import JSONResponse
 from starlette.responses import StreamingResponse
 from pydantic import BaseModel, field_validator, model_validator
 
@@ -18,30 +17,23 @@ from app.db import get_logs, get_logs_before, get_all_sessions
 from app.deps import manager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
 
 logger = logging.getLogger("orchestra.sessions")
 
 router = APIRouter()
 
-MERGE_IDLE_GRACE_SECONDS = 2.0
-MERGE_IDLE_POLL_SECONDS = 0.05
-
-
 async def _wait_for_merge_idle(session) -> bool:
-    """Absorb the short DONE-message → turn-end transition before merging."""
-    if not session.loaded or session.status.value != "running":
+    """Wait for the current turn's explicit terminal signal; only IDLE is ready."""
+    if session.status.value == "idle":
         return True
-    attempts = max(1, ceil(MERGE_IDLE_GRACE_SECONDS / MERGE_IDLE_POLL_SECONDS))
-    for _ in range(attempts):
-        await asyncio.sleep(MERGE_IDLE_POLL_SECONDS)
-        if session.status.value != "running":
-            return True
-    return False
+    if not session.loaded or session.status.value != "running":
+        return False
+    return await session.wait_for_turn_completion()
 
 
 def _session_base_branch(session, requested: str = "") -> str:
     """Resolve an explicit or persisted lifecycle base against the actual repository."""
     from app.workspace import resolve_base_branch
 
     worktree_path = session.worktree_path
     if not worktree_path:
@@ -674,22 +666,34 @@ async def merge_session(name: str, req: dict):
     if not scope:
         return JSONResponse({"error": "session has no scope"}, status_code=400)
     try:
         target = _session_base_branch(found, requested_target)
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=400)
     async with manager.get_session_lock(session_id):
         if not await _wait_for_merge_idle(found):
-            return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
+            status = found.status.value
+            return JSONResponse(
+                {"error": f"worker is {status} — wait for idle before merge"},
+                status_code=400,
+            )
         async with AsyncExitStack() as stack:
             if found.loaded:
                 await stack.enter_async_context(found._lifecycle_lock)
-                if found.status.value == "running":
-                    return JSONResponse({"error": "worker is running — wait for idle before merge"}, status_code=400)
+                if found.status.value != "idle":
+                    return JSONResponse(
+                        {
+                            "error": (
+                                f"worker is {found.status.value} — "
+                                "wait for idle before merge"
+                            )
+                        },
+                        status_code=400,
+                    )
             try:
                 result = await asyncio.to_thread(merge_worktree_to_main, worktree_path, scope, target_branch=target)
                 if result.get("ok"):
                     link_results = {}
                     with _tm._conn() as _lc:
                         _proj = _tm.get_project_by_scope(_lc, scope)
                     _link_project_id = _proj["id"] if _proj else ""
                     for task_ref, commits in result.pop("merged_commits", {}).items():
@@ -755,45 +759,66 @@ async def switch_branch(name: str, req: dict):
         return JSONResponse({"error": "task_id required"}, status_code=400)
     try:
         par = _normalize_task_id(task_id)
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=400)
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
-    if found.loaded and found.status.value == "running":
-        return JSONResponse({"error": "worker is running — wait for idle"}, status_code=400)
     worktree_path = found.worktree_path
     session_id = found.id
     if not worktree_path:
         return JSONResponse({"error": "session has no worktree"}, status_code=400)
     new_branch = f"task-{par}/{name}"
     try:
         from_ref = _session_base_branch(found, req.get("from_ref", ""))
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=400)
     async with manager.get_session_lock(session_id):
-        try:
-            result = await asyncio.to_thread(switch_worktree_branch, worktree_path, new_branch, from_ref=from_ref)
-            if result.get("ok") or result.get("branch"):
-                await manager.persist_lifecycle(
-                    found,
-                    branch=result.get("branch", new_branch),
-                    base_branch=from_ref,
-                    task_id=par,
-                    needs_switch=False,
-                )
+        if not await _wait_for_merge_idle(found):
+            return JSONResponse(
+                {"error": f"worker is {found.status.value} — wait for idle before switch"},
+                status_code=400,
+            )
+        async with AsyncExitStack() as stack:
+            if found.loaded:
+                await stack.enter_async_context(found._lifecycle_lock)
+                if found.status.value != "idle":
+                    return JSONResponse(
+                        {
+                            "error": (
+                                f"worker is {found.status.value} — "
+                                "wait for idle before switch"
+                            )
+                        },
+                        status_code=400,
+                    )
             try:
-                _tm.api_update_task(par, status="in_progress")
+                result = await asyncio.to_thread(
+                    switch_worktree_branch,
+                    worktree_path,
+                    new_branch,
+                    from_ref=from_ref,
+                )
+                if result.get("ok") or result.get("branch"):
+                    await manager.persist_lifecycle(
+                        found,
+                        branch=result.get("branch", new_branch),
+                        base_branch=from_ref,
+                        task_id=par,
+                        needs_switch=False,
+                    )
+                try:
+                    _tm.api_update_task(par, status="in_progress")
+                except Exception as e:
+                    logger.warning(f"task #{par} → in_progress failed after switch-branch: {e}")
+                return result
             except Exception as e:
-                logger.warning(f"task #{par} → in_progress failed after switch-branch: {e}")
-            return result
-        except Exception as e:
-            return JSONResponse({"error": str(e)}, status_code=500)
+                return JSONResponse({"error": str(e)}, status_code=500)
 
 
 @router.get("/api/sessions/{name}/wip")
 async def session_wip(name: str, scope: str = "", base_ref: str = ""):
     from app.workspace import branch_wip_status
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
diff --git a/app/session.py b/app/session.py
index 994b84702..e5319e2c8 100644
--- a/app/session.py
+++ b/app/session.py
@@ -197,16 +197,17 @@ class AgentSession:
     _session_cost: float = field(default=0.0, repr=False)
     _last_cost_cached: float = field(default=0.0, repr=False)
     _last_turn_ok: bool = field(default=True, repr=False)
     _last_stop_reason: str = field(default="", repr=False)
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _persist_dirty: bool = field(default=False, repr=False)
     _turn_gen: int = field(default=0, repr=False)
+    _turn_finished_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
     _spawn_repo_path: str = field(default="", repr=False)
     _spawn_git_common_dir: str = field(default="", repr=False)
     _auto_continue_count: int = field(default=0, repr=False)
     _rate_limit_retries: int = field(default=0, repr=False)
     _server_error_retries: int = field(default=0, repr=False)
     _session_limit_hit: bool = field(default=False, repr=False)
@@ -442,16 +443,22 @@ class AgentSession:
 
     async def start(self, initial_message: str | None = None) -> None:
         if initial_message:
             await self.send(initial_message)
         else:
             self.status = AgentStatus.IDLE
             self._persist()
 
+    async def wait_for_turn_completion(self) -> bool:
+        """Wait for the active logical turn to publish its terminal status."""
+        while self.status == AgentStatus.RUNNING:
+            await self._turn_finished_event.wait()
+        return self.status == AgentStatus.IDLE
+
     async def send(self, message: str) -> None:
         original_user_message = message
         # Retry budgets belong to one logical request. A real new message resets both;
         # each internal retry preserves only its own failure class.
         if not message.startswith("[system] Retrying after rate limit."):
             self._rate_limit_retries = 0
         if not message.startswith("[system] Retrying after transient server error."):
             self._server_error_retries = 0
@@ -539,16 +546,17 @@ class AgentSession:
                 self._persist()
                 asyncio.create_task(self._notify_scope_running())
 
             try:
                 backend = await self._ensure_backend()
             except Exception:
                 self.status = AgentStatus.IDLE
                 self._persist()
+                self._turns.publish_turn_finished()
                 raise
 
             # Claude transcripts are local files. A DB row can outlive that file (old
             # manual stops/cleanup), in which case Claude CLI cannot resume the UUID.
             # ClaudeBackend reconnects fresh; carry a bounded DB transcript explicitly
             # so the new session does not wake up amnesiac or keep returning HTTP 500.
             if getattr(backend, "resume_failed", False):
                 self.runtime_handoff = await self._build_runtime_handoff(
@@ -592,16 +600,17 @@ class AgentSession:
                     "</current-user-message>"
                 )
             try:
                 await backend.send(outbound_message)
             except Exception:
                 if self.status == AgentStatus.RUNNING:
                     self.status = AgentStatus.IDLE
                     self._persist()
+                    self._turns.publish_turn_finished()
                 raise
             if pending_handoff and self.runtime_handoff == pending_handoff:
                 self.runtime_handoff = ""
                 self._persist()
 
             if did_inject:
                 if templates_changed:
                     self._log("status", f"prompt updated → {pending_th}")
@@ -681,16 +690,17 @@ class AgentSession:
             if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                 logger.error(f"[{self.name}] reconnect limit reached ({consecutive_failures} consecutive failures), giving up")
                 self._log("error", f"backend unstable: {consecutive_failures} consecutive failures, giving up")
                 self._turn_start = 0
                 await self._disconnect_backend()
                 if self.status == AgentStatus.RUNNING:
                     self.status = AgentStatus.IDLE
                     self._persist()
+                    self._turns.publish_turn_finished()
                 return
 
             try:
                 if self._backend is None:
                     return
                 await self._backend.reconnect()
                 logger.info(f"[{self.name}] listener reconnected after error")
                 self._log("status", "listener reconnected")
@@ -699,16 +709,17 @@ class AgentSession:
                 continue
             except Exception as re_err:
                 logger.error(f"[{self.name}] listener reconnect failed: {re_err}")
                 self._log("error", f"listener reconnect failed: {re_err}")
                 self._backend = None
                 if self.status == AgentStatus.RUNNING:
                     self.status = AgentStatus.IDLE
                     self._persist()
+                    self._turns.publish_turn_finished()
                 return
 
     async def _turn_event_loop(self) -> None:
         logger.info(f"[{self.name}] {self.backend_type} turn started")
         try:
             async for event in self._backend.events():
                 self._last_msg_time = asyncio.get_event_loop().time()
                 # thread.started is emitted before turn.completed. Store it now so an
@@ -882,16 +893,17 @@ class AgentSession:
                 if get_runtime(self.backend_type).capabilities.event_stream == "per_turn":
                     self._listen_task = asyncio.create_task(self._turn_event_loop())
                     self._listen_task.add_done_callback(self._on_task_done)
         except Exception as e:
             logger.error(f"[{self.name}] flush pending failed: {e}")
             self._pending_messages[0:0] = msgs
             self.status = AgentStatus.IDLE
             self._persist()
+            self._turns.publish_turn_finished()
 
     def _on_task_done(self, task: asyncio.Task) -> None:
         try:
             exc = task.exception()
         except asyncio.CancelledError:
             return
         if exc:
             import traceback
@@ -904,32 +916,35 @@ class AgentSession:
             self._persist()
         else:
             logger.warning(f"[{self.name}] listen task exited without exception (silent death), status={self.status}")
             if self.status == AgentStatus.RUNNING:
                 self._log("error", "listen task exited unexpectedly while RUNNING")
                 self._turn_start = 0
                 self.status = AgentStatus.IDLE
                 self._persist()
+        if self.status != AgentStatus.RUNNING and self._auto_continue_count == 0:
+            self._turns.publish_turn_finished()
 
     # ── Session operations ──
 
     async def interrupt(self) -> None:
         async with self._lifecycle_lock:
             backend = self._backend if self.status == AgentStatus.RUNNING else None
             # Publish the stop before waiting for the SDK control acknowledgement. This
             # prevents concurrent messages from being injected into the turn being
             # interrupted; they will start a clean turn after this lock is released.
             self._turns.cancel_auto_report()
             self._cancel_precompact_timer("interrupt")
             self._turn_start = 0
             self._manually_interrupted = True
             self.status = AgentStatus.IDLE
             self._log("status", "interrupted")
             self._persist()
+            self._turns.publish_turn_finished()
 
             if backend:
                 acknowledged = await backend.interrupt()
                 if acknowledged is False and self._backend is backend:
                     self._log("error", "interrupt was not acknowledged; disconnecting backend")
                     await self._disconnect_backend()
 
     async def _compact_codex_context(self) -> dict:
@@ -1171,24 +1186,26 @@ class AgentSession:
                 await asyncio.wait_for(ack_event.wait(), timeout=60)
             except asyncio.TimeoutError:
                 self._log("error", "compact ack turn did not complete (60s)")
                 # stop the still-running ack turn so it can't interleave with the next send
                 await self._disconnect_backend()
                 self.session_id = pre_compact_session_id
                 self.status = AgentStatus.IDLE
                 self._persist()
+                self._turns.publish_turn_finished()
                 return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
             if self._session_limit_hit:
                 error = "Claude subscription limit hit during compact acknowledgement"
                 self._log("error", error)
                 await self._disconnect_backend()
                 self.session_id = pre_compact_session_id
                 self.status = AgentStatus.IDLE
                 self._persist()
+                self._turns.publish_turn_finished()
                 return {"ok": False, "error": error, "before_pct": before_pct}
         finally:
             self._compact_ack_event = None
             self._compact_ack_gen = -1
             self._compacting = False
             if self._pending_messages:
                 self._spawn_bg(self._flush_pending())
 
@@ -1231,16 +1248,17 @@ class AgentSession:
         await asyncio.sleep(delay)
         try:
             await self.send("[system] Retrying after rate limit. Continue where you left off.")
             logger.info(f"[{self.name}] rate-limit retry after {delay}s")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
+            self._turns.publish_turn_finished()
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
         await asyncio.sleep(delay)
         try:
             async with self._lifecycle_lock:
                 # A real user message already started a newer turn; it supersedes this
                 # automatic retry and must not be duplicated.
@@ -1252,26 +1270,28 @@ class AgentSession:
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now."
             )
             logger.info(f"[{self.name}] server-error retry after {delay}s")
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
+            self._turns.publish_turn_finished()
 
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             await self.send("[system] Turn limit reached. Continue where you left off.")
             logger.info(f"[{self.name}] auto-continue after max_turns")
         except Exception as e:
             logger.warning(f"[{self.name}] auto-continue failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
+            self._turns.publish_turn_finished()
 
     async def _refresh_context_from_api(self) -> None:
         if not self._backend or not hasattr(self._backend, 'context_usage'):
             return
         try:
             usage = await asyncio.wait_for(self._backend.context_usage(), timeout=5)
             if usage and usage.get("percentage") is not None:
                 old_pct = self._last_context.get("percentage", 0)
@@ -1423,16 +1443,17 @@ class AgentSession:
     async def stop(self) -> None:
         self._log("status", "⏹️ stopped (manual interrupt)")
         self._turns.cancel_auto_report()
         self._cancel_precompact_timer("stop")
         await self._disconnect_backend()
         self._hibernated = False
         self.status = AgentStatus.IDLE
         self._persist()
+        self._turns.publish_turn_finished()
 
     def _persist(self) -> None:
         # Coalesce rapid successive calls: mark dirty, let one active task drain them all —
         # prevents N DB writes when status/cost/context all change in the same event loop tick
         self._persist_dirty = True
         if self._persist_task and not self._persist_task.done():
             return
         self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
diff --git a/app/session_turns.py b/app/session_turns.py
index 3f9dab0ef..7137ce5a3 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -72,18 +72,22 @@ class TurnManager:
         s = self.s
         if s._auto_report_task and not s._auto_report_task.done():
             s._auto_report_task.cancel()
         s._auto_report_task = None
 
     def bump_turn_gen(self) -> None:
         """Новый ход начался — инвалидируем отложенный авто-репорт прошлого хода."""
         self.s._turn_gen += 1
+        self.s._turn_finished_event.clear()
         self.cancel_auto_report()
 
+    def publish_turn_finished(self) -> None:
+        self.s._turn_finished_event.set()
+
     def fire_auto_report(self) -> None:
         """Send auto-report to parent immediately when worker goes idle.
         Orchestrators don't auto-report — they reply to user directly.
         Skipped if worker already sent explicit send_message, has pending messages,
         completed a successful silent turn, or was interrupted/stopped by user.
 
         Without this, silent workers (those that don't call send_message) would
         leave the orchestrator waiting forever for a signal that never comes.
@@ -217,16 +221,17 @@ class TurnManager:
         if bg_manager and bg_manager.has_active_jobs(s.id):
             s.status = AgentStatus.WAITING
             s._log("status", "waiting for bg jobs")
         else:
             s.status = AgentStatus.IDLE
             s.progress_pct = 0
             s.progress_status = ""
         s._persist()
+        self.publish_turn_finished()
 
     def after_turn_idle_actions(
             self, live_pct: int, *, allow_auto_report: bool = True,
             allow_precompact: bool = True) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         s = self.s
         if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
             s._compact_ack_event.set()
diff --git a/tests/test_api.py b/tests/test_api.py
index 958ed8f4d..437873e0f 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -383,16 +383,17 @@ async def test_merge_links_commits_with_normalized_sqlite_results(db, monkeypatc
     from app import tm
 
     with tm._conn() as conn:
         tm.ensure_project(conn, "project", scope="/s")
         task = tm.create_task(conn, "project", "Link target", par_number=90)
 
     class FakeSession:
         loaded = False
+        status = type("Status", (), {"value": "idle"})()
         worktree_path = "/wt"
         scope = "/s"
         id = "link-results"
         name = "worker"
         branch = "task-90/worker"
 
     session = FakeSession()
 
@@ -556,16 +557,17 @@ async def test_send_auto_switch_uses_and_persists_base(monkeypatch):
 async def test_switch_uses_persisted_base_when_from_ref_is_omitted(monkeypatch):
     import app.main as mainmod
     import app.routes.sessions as sessmod
 
     session = type("Session", (), {
         "id": "sid",
         "name": "w",
         "loaded": False,
+        "status": type("Status", (), {"value": "idle"})(),
         "worktree_path": "/wt",
         "base_branch": "master",
     })()
     captured = {}
 
     def fake_switch(_wt, new_branch, from_ref=""):
         captured.update(new_branch=new_branch, from_ref=from_ref)
         return {"ok": True, "branch": new_branch}
@@ -603,86 +605,173 @@ async def test_merge_waits_for_running_worker_to_finish_turn(db, monkeypatch):
         loaded = True
         status = Status()
         _lifecycle_lock = asyncio.Lock()
         worktree_path = "/wt"
         scope = "/s"
         id = "merge-finish"
         name = "w"
 
-        def _persist(self):
-            pass
+        async def wait_for_turn_completion(self):
+            wait_started.set()
+            await turn_finished.wait()
+            return self.status.value == "idle"
+
+        async def interrupt(self):
+            raise AssertionError("merge must not interrupt the worker")
 
     session = FakeSession()
     merge_called = False
-
-    async def finish_turn(_delay):
-        session.status.value = "idle"
+    wait_started = asyncio.Event()
+    turn_finished = asyncio.Event()
 
     def fake_merge(*_args, **_kwargs):
         nonlocal merge_called
         merge_called = True
         return {"ok": True, "merged_commits": {}}
 
-    monkeypatch.setattr(sessmod.asyncio, "sleep", finish_turn)
     monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
     monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
 
     async def persist_lifecycle(_session, **_fields):
         return None
 
     monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
 
-    result = await sessmod.merge_session("w", {"scope": "/s"})
+    merge_task = asyncio.create_task(
+        sessmod.merge_session("w", {"scope": "/s"}),
+    )
+    await asyncio.wait_for(wait_started.wait(), timeout=0.2)
+    assert merge_called is False
+    assert merge_task.done() is False
+
+    session.status.value = "idle"
+    turn_finished.set()
+    result = await asyncio.wait_for(merge_task, timeout=0.2)
 
     assert result["ok"] is True
     assert merge_called is True
 
 
 @pytest.mark.asyncio
-async def test_merge_rejects_worker_that_stays_running_without_merging(monkeypatch):
+async def test_merge_rejects_waiting_worker_without_merging(monkeypatch):
     import asyncio
     import app.main as mainmod
     import app.routes.sessions as sessmod
 
     class Status:
-        value = "running"
+        value = "waiting"
 
     class FakeSession:
         loaded = True
         status = Status()
         _lifecycle_lock = asyncio.Lock()
         worktree_path = "/wt"
         scope = "/s"
         id = "merge-running"
         name = "w"
 
     session = FakeSession()
     merge_called = False
 
-    async def no_wall_clock_wait(_delay):
-        return None
-
     def fake_merge(*_args, **_kwargs):
         nonlocal merge_called
         merge_called = True
         return {"ok": True, "merged_commits": {}}
 
-    monkeypatch.setattr(sessmod.asyncio, "sleep", no_wall_clock_wait)
     monkeypatch.setattr("app.workspace.merge_worktree_to_main", fake_merge)
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: session)
     monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "master")
 
     response = await sessmod.merge_session("w", {"scope": "/s"})
 
     assert response.status_code == 400
+    assert "waiting" in response.body.decode()
     assert merge_called is False
 
 
+@pytest.mark.asyncio
+async def test_switch_waits_for_running_worker_to_finish_turn(db, monkeypatch):
+    import asyncio
+    import app.main as mainmod
+    import app.routes.sessions as sessmod
+
+    class Status:
+        value = "running"
+
+    class FakeSession:
+        loaded = True
+        status = Status()
+        worktree_path = "/wt"
+        scope = "/s"
+        id = "switch-finish"
+        name = "w"
+        base_branch = "main"
+        _lifecycle_lock = asyncio.Lock()
+
+        async def wait_for_turn_completion(self):
+            wait_started.set()
+            await turn_finished.wait()
+            return self.status.value == "idle"
+
+        async def interrupt(self):
+            raise AssertionError("switch must not interrupt the worker")
+
+    session = FakeSession()
+    wait_started = asyncio.Event()
+    turn_finished = asyncio.Event()
+    switch_called = False
+
+    def fake_switch(*_args, **_kwargs):
+        nonlocal switch_called
+        switch_called = True
+        return {"ok": True, "branch": "task-91/w"}
+
+    async def persist_lifecycle(found, **fields):
+        for key, value in fields.items():
+            setattr(found, key, value)
+
+    monkeypatch.setattr(mainmod.manager, "get_by_name", lambda *_args: session)
+    monkeypatch.setattr(mainmod.manager, "persist_lifecycle", persist_lifecycle)
+    monkeypatch.setattr(sessmod, "_session_base_branch", lambda *_args: "main")
+    monkeypatch.setattr("app.workspace.switch_worktree_branch", fake_switch)
+    monkeypatch.setattr("app.tm.api_update_task", lambda *_args, **_kwargs: None)
+
+    switch_task = asyncio.create_task(
+        sessmod.switch_branch("w", {"scope": "/s", "task_id": "91"}),
+    )
+    await asyncio.wait_for(wait_started.wait(), timeout=0.2)
+    assert switch_called is False
+    assert switch_task.done() is False
+
+    interrupt_status_published = asyncio.Event()
+    interrupt_ack = asyncio.Event()
+
+    async def finish_interrupt():
+        async with session._lifecycle_lock:
+            session.status.value = "idle"
+            turn_finished.set()
+            interrupt_status_published.set()
+            await interrupt_ack.wait()
+
+    interrupt_task = asyncio.create_task(finish_interrupt())
+    await asyncio.wait_for(interrupt_status_published.wait(), timeout=0.2)
+    await asyncio.sleep(0)
+    assert switch_called is False
+    assert switch_task.done() is False
+
+    interrupt_ack.set()
+    await asyncio.wait_for(interrupt_task, timeout=0.2)
+    result = await asyncio.wait_for(switch_task, timeout=0.2)
+
+    assert result["ok"] is True
+    assert switch_called is True
+
+
 @pytest.mark.asyncio
 async def test_merge_and_switch_hold_lifecycle_lock_against_worker_wakeup(db, monkeypatch):
     import asyncio
     import threading
     import app.main as mainmod
     import app.routes.sessions as sessmod
 
     observed = {"persist_locked": []}
diff --git a/tests/test_session.py b/tests/test_session.py
index 7f73bf4b7..b2a25e543 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -304,16 +304,135 @@ class TestSend:
             assert second_injected or second_queued, "второй send должен быть либо инжектирован, либо в очереди"
 
             backend.finish()
             await send_task
             await asyncio.sleep(0.1)
 
 
 class TestTurn:
+    @pytest.mark.parametrize("runtime_id", ("claude", "codex", "grok", "opencode"))
+    @pytest.mark.asyncio
+    async def test_turn_completion_signal_follows_persist_for_every_runtime(
+        self, session, monkeypatch, runtime_id,
+    ):
+        from app.events import AgentEvent
+        from app.runtime_registry import get_runtime
+        from app.session import AgentStatus
+
+        class OneTurnBackend:
+            async def events(self):
+                yield AgentEvent(
+                    type="turn_end",
+                    metadata={
+                        "ok": True,
+                        "stop_reason": "end_turn",
+                        "num_turns": 1,
+                        "cost_usd": 0,
+                    },
+                )
+
+        observed = []
+        runtime = get_runtime(runtime_id)
+        session.backend_type = runtime_id
+        session._backend = OneTurnBackend()
+        session._log = lambda *_args, **_kwargs: None
+        session._turns.bump_turn_gen()
+        session.status = AgentStatus.RUNNING
+        monkeypatch.setattr(
+            session,
+            "_persist",
+            lambda: observed.append(
+                (session.status, session._turn_finished_event.is_set())
+            ),
+        )
+        monkeypatch.setattr(
+            session._turns,
+            "after_turn_idle_actions",
+            lambda *_args, **_kwargs: None,
+        )
+
+        def discard_background(coroutine):
+            coroutine.close()
+
+        monkeypatch.setattr(session, "_spawn_bg", discard_background)
+
+        waiter = asyncio.create_task(session.wait_for_turn_completion())
+        await asyncio.sleep(0)
+        assert waiter.done() is False
+
+        if runtime.capabilities.event_stream == "persistent":
+            await session._persistent_event_loop()
+        else:
+            await session._turn_event_loop()
+
+        assert observed == [(AgentStatus.IDLE, False)]
+        assert await asyncio.wait_for(waiter, timeout=0.2) is True
+        assert session._turn_finished_event.is_set() is True
+
+    @pytest.mark.asyncio
+    async def test_waiting_status_finishes_turn_but_is_not_merge_ready(
+        self, session, monkeypatch,
+    ):
+        from app.session import AgentStatus
+
+        class ActiveJobs:
+            def has_active_jobs(self, _session_id):
+                return True
+
+        monkeypatch.setattr("app.bg_jobs.bg_manager", ActiveJobs())
+        session._log = lambda *_args, **_kwargs: None
+        session._turns.bump_turn_gen()
+        session.status = AgentStatus.RUNNING
+        monkeypatch.setattr(session, "_persist", lambda: None)
+
+        waiter = asyncio.create_task(session.wait_for_turn_completion())
+        await asyncio.sleep(0)
+        session._turns.finish_turn_status()
+
+        assert await asyncio.wait_for(waiter, timeout=0.2) is False
+        assert session.status is AgentStatus.WAITING
+
+    @pytest.mark.asyncio
+    async def test_auto_continue_segment_does_not_publish_terminal_signal(
+        self, session, monkeypatch,
+    ):
+        from app.events import AgentEvent
+        from app.session import AgentStatus
+
+        session.backend_type = "codex"
+        session._log = lambda *_args, **_kwargs: None
+        session._turns.bump_turn_gen()
+        session.status = AgentStatus.RUNNING
+        monkeypatch.setattr(session, "_persist", lambda: None)
+
+        def discard_background(coroutine):
+            coroutine.close()
+
+        monkeypatch.setattr(session, "_spawn_bg", discard_background)
+        waiter = asyncio.create_task(session.wait_for_turn_completion())
+        await asyncio.sleep(0)
+
+        session._handle_event(AgentEvent(
+            type="turn_end",
+            metadata={
+                "ok": True,
+                "stop_reason": "max_turns",
+                "num_turns": 5,
+                "cost_usd": 0,
+            },
+        ))
+
+        assert session.status is AgentStatus.RUNNING
+        assert session._turn_finished_event.is_set() is False
+        assert waiter.done() is False
+        waiter.cancel()
+        with pytest.raises(asyncio.CancelledError):
+            await waiter
+
     @pytest.mark.asyncio
     async def test_turn_end_returns_to_idle(self, session):
         """После turn_end event статус возвращается в IDLE."""
         from app.session import AgentStatus
         backend = _MockBackend()
 
         with patch.object(session, "_make_backend", return_value=backend):
             send_task = asyncio.create_task(session.send("task"))


## LATER FIX e2e83139f4 (39.0 days later): fix: complete scoped recovery and continuation lifecycle safeguards
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: complete scoped recovery and continuation lifecycle safeguards


diff --git a/app/manager.py b/app/manager.py
index 9ba94dbb6..758a1f3a4 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -2356,28 +2356,33 @@ class SessionManager:
     # промпт берётся отдельным роутом `GET /api/sessions/{name}/prompt` по кнопке 📜,
     # а `last_summary` нужен только серверу (`runtime_handoff`).
     # Понадобилось поле в списке — добавляй осознанно и перемеряй вес: tests/test_manager.py::TestListSessions
     # держит потолок.
     _LIST_OMIT = ("system_prompt", "prompt_overlay", "last_summary")
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
+        from app.message_deliveries import targets_with_uncertain_delivery
         result = []
         seen = set()
         for s in self.sessions.values():
             if scope is None or s.scope == scope:
                 result.append(s.to_dict())
                 seen.add(s.id)
         for row in get_all_sessions(scope):
             if row["id"] not in seen:
                 result.append(row)
         # Cache-timer metadata is runtime-derived; Codex exposes only an approximate window.
         turn_map = get_last_turn_map()
+        uncertain_targets = targets_with_uncertain_delivery()
         for r in result:
+            r.setdefault("runtime_connection", "not_loaded")
+            if r["id"] in uncertain_targets:
+                r["delivery_uncertain"] = True
             r["last_turn_ts"] = turn_map.get(r["id"])
             r.update(cache_policy_for_runtime(runtime_for_record(r)))
             lifecycle = self.lifecycle_quarantine(r)
             if lifecycle:
                 r["status"] = "quarantined"
                 r["lifecycle_status"] = lifecycle
             for omit in self._LIST_OMIT:
                 r.pop(omit, None)
diff --git a/app/message_deliveries.py b/app/message_deliveries.py
index cef9d49b0..650047e6e 100644
--- a/app/message_deliveries.py
+++ b/app/message_deliveries.py
@@ -79,17 +79,18 @@ def _queue_block(row: sqlite3.Row | dict) -> dict:
         "arguments": {"delivery_id": head["delivery_id"]},
         "blocked_since": head["updated_at"],
         "retryable": False,
         "message": (
             f"Message accepted but NOT delivered: the target queue has been blocked "
             f"since {head['updated_at']} by delivery {head['delivery_id']}, whose "
             "provider outcome is still unknown. Nothing queued after it moves while "
             "that outcome could still change. Do not resend this message: the next "
-            "restart settles the head and the queue drains on its own."
+                "operator can restart only the target CLI to release the queue; "
+                "the ambiguous message will NOT be resent."
         ),
     }
 
 
 def _next_action(row: sqlite3.Row | dict) -> dict:
     # Блокировка очереди едет в `next_action`, а не отдельным ключом: это единственное
     # поле receipt'а, которое читают потребители остальных доставок и мержей, — второй
     # носитель той же мысли просто никто бы не открыл.
@@ -493,16 +494,24 @@ class MessageDeliveryContext:
 # который мог дослать сообщение, мёртв, поэтому переставить порядок оно уже не может —
 # а именно перестановки и дубля барьер и не допускает. Исход так и остался неизвестным,
 # и запись об этом хранит состояние; блокировать очередь ему больше незачем.
 _TERMINAL_DELIVERY_STATES = (
     "SUBMITTED", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN_ORPHANED",
 )
 
 
+def targets_with_uncertain_delivery() -> set[str]:
+    """One batch projection for the session list, not one DB query per worker."""
+    with db._conn() as connection:
+        return {row[0] for row in connection.execute(
+            "SELECT DISTINCT target_session_id FROM message_deliveries WHERE state='DELIVERY_UNKNOWN'"
+        )}
+
+
 def _next_target_delivery(target_session_id: str) -> sqlite3.Row | None:
     placeholders = ",".join("?" * len(_TERMINAL_DELIVERY_STATES))
     with db._conn() as connection:
         return connection.execute(
             f"""SELECT * FROM message_deliveries
                WHERE target_session_id=? AND state NOT IN ({placeholders})
                ORDER BY accept_seq LIMIT 1""",
             (target_session_id, *_TERMINAL_DELIVERY_STATES),
@@ -620,43 +629,59 @@ def _observe_target_runner(task: asyncio.Task[bool]) -> None:
             logger.exception("message delivery runner failed")
     if target is None or not drained:
         return
     head = _next_target_delivery(target)
     if head is not None and head["state"] in {"QUEUED", "PREPARING"}:
         ensure_target_runner(target)
 
 
-async def recover_message_deliveries() -> None:
+def _recover_message_deliveries(target_session_id: str | None) -> tuple[set[str], int]:
+    if target_session_id == "":
+        raise ValueError("target session id must not be empty")
     with db._conn() as connection:
         connection.execute("BEGIN IMMEDIATE")
         orphan_error = RuntimeError("orphaned provider dispatch")
         orphan_error_json = json.dumps(
             {
                 "code": "DELIVERY_OUTCOME_UNKNOWN",
                 "message": (
-                    "Server restarted while provider acceptance was in flight; delivery may "
+                    "Dispatch runtime was stopped while provider acceptance was uncertain; delivery may "
                     "already have been accepted."
                 ),
                 "retryable": False,
                 "outcome_unknown": True,
                 "details": {
                     "phase": "PROVIDER_CALL_STARTED",
                     "exception_type": type(orphan_error).__name__,
                 },
             },
             ensure_ascii=False,
             sort_keys=True,
             separators=(",", ":"),
         )
-        connection.execute(
+        scope_sql = " AND target_session_id=?" if target_session_id is not None else ""
+        scope_args = (target_session_id,) if target_session_id is not None else ()
+        settled = connection.execute(
             """UPDATE message_deliveries
                SET state='DELIVERY_UNKNOWN_ORPHANED', error_json=?, updated_at=?
-               WHERE state IN ('DISPATCHING','DELIVERY_UNKNOWN')""",
-            (orphan_error_json, _now()),
-        )
+               WHERE state IN ('DISPATCHING','DELIVERY_UNKNOWN')""" + scope_sql,
+            (orphan_error_json, _now(), *scope_args),
+        ).rowcount
         rows = connection.execute(
             """SELECT target_session_id FROM message_deliveries
-               WHERE state IN ('QUEUED','PREPARING') ORDER BY accept_seq"""
+               WHERE state IN ('QUEUED','PREPARING')""" + scope_sql + " ORDER BY accept_seq",
+            scope_args,
         ).fetchall()
         targets = {row["target_session_id"] for row in rows}
+    return targets, settled
+
+
+async def recover_message_deliveries(*, target_session_id: str | None = None) -> int:
+    """After runtime teardown, release ambiguous barriers without retrying their payloads.
+
+    Targeted callers must exclude dispatch and new sends until teardown and this
+    transaction finish. The unscoped caller is startup, before dispatch starts.
+    """
+    targets, settled = await asyncio.to_thread(_recover_message_deliveries, target_session_id)
     for target in targets:
         ensure_target_runner(target)
+    return settled
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 93a71b2d0..e2752fd05 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -1284,25 +1284,48 @@ async def rollback_session(name: str, req: ScopeRequest, index: int = -1):
         "runtime": session.backend_type,
         "model": session.model,
         "compacted_at": entry.get("compacted_at"),
     }
 
 
 @router.post("/api/sessions/{name}/restart-cli")
 async def restart_cli(name: str, req: ScopeRequest):
+    from app import message_deliveries
+    from app.manager import _wait_owned_task
+
     session = await manager.ensure_loaded(name, req.scope)
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
-    await session._disconnect_backend()
-    session.status = AgentStatus.IDLE
-    session._persist()
-    if session._pending_messages:
-        session._spawn_bg(session._flush_pending())
-    return {"ok": True}
+    delivery_lock = message_deliveries._target_delivery_locks.setdefault(session.id, asyncio.Lock())
+    manager_lock = manager.get_session_lock(session.id)
+    # Fail before mutation, rather than queue a restart behind a send and then
+    # unexpectedly interrupt the newly started turn. Uncontended asyncio locks
+    # acquire without yielding; this order matches the delivery runner.
+    async def restart_locked():
+        locks = (delivery_lock, manager_lock, session._lifecycle_lock)
+        if any(lock.locked() for lock in locks):
+            return JSONResponse({"error": "target is busy; CLI restart made no changes"}, status_code=409)
+        async with delivery_lock, manager_lock, session._lifecycle_lock:
+            session._turn_start_cancel_gen += 1
+            session._manually_interrupted = True
+            session._cancel_precompact_timer("restart_cli")
+            await session._disconnect_backend()
+            settled = await message_deliveries.recover_message_deliveries(target_session_id=session.id)
+            session.status = AgentStatus.IDLE
+            session._persist()
+        if session._pending_messages:
+            session._spawn_bg(session._flush_pending())
+        return {"ok": True, "unreconciled_deliveries": settled}
+
+    # A disconnected HTTP client must not release the locks while a SQLite
+    # recovery thread or runtime teardown is still operating on this session.
+    task = asyncio.create_task(restart_locked())
+    await _wait_owned_task(task)
+    return task.result()
 
 
 @router.post("/api/sessions/{name}/clear-session")
 async def clear_session(name: str, req: ScopeRequest):
     """Drop the conversation thread: next turn starts with an empty history.
 
     Unlike restart-cli (reconnects the backend but keeps session_id), this
     forgets the thread entirely. The worktree, branch and prompt are untouched.
diff --git a/app/session.py b/app/session.py
index 2f1237e80..9e9715686 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1307,17 +1307,19 @@ class AgentSession:
 
         while True:
             await self._lifecycle_lock.acquire()
             # Recheck after admission too: Stop or a newer turn can win while
             # this sender is outside the lock waiting for quota data.
             if retry_generation is not None and (
                 retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
                 or self._manually_interrupted
-                or self.status != AgentStatus.IDLE
+                or (self.status != AgentStatus.IDLE
+                    and not (provenance.subtype in {"turn_limit_continue", "runtime_reconnect"}
+                             and self.status == AgentStatus.RUNNING))
                 or self._compacting
             ):
                 self._lifecycle_lock.release()
                 return
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
@@ -1358,17 +1360,17 @@ class AgentSession:
             if (
                 delivery is not None
                 and not allow_running_delivery
                 and (self._compacting or self.status == AgentStatus.RUNNING)
             ):
                 raise RuntimeError("initial delivery requires an idle session")
             # Both failure classes share the logical request: alternating upstream
             # errors must not replenish each other's retry budget.
-            if provenance.subtype not in {"rate_limit_retry", "server_error_retry"}:
+            if provenance.subtype not in {"rate_limit_retry", "server_error_retry", "runtime_reconnect"}:
                 self._rate_limit_retries = 0
                 self._server_error_retries = 0
             if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
             self._safeguard_refusal = ""
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
@@ -2336,35 +2338,46 @@ class AgentSession:
                 self._finish_failed_running_turn(
                     "backend unstable after repeated listener failures"
                 )
                 return
 
             try:
                 if self._backend is None:
                     return
+                generation = (self._turn_gen, self._turn_start_cancel_gen)
                 await self._reconnect_backend()
+                if generation != (self._turn_gen, self._turn_start_cancel_gen) or self._manually_interrupted:
+                    continue
                 logger.info(f"[{self.name}] listener reconnected after error")
                 self._log("status", "listener reconnected")
                 backend = self._backend
                 if (
                     self.status == AgentStatus.RUNNING
                     and hasattr(backend, "active_turn_id")
                     and not getattr(backend, "active_turn_id", None)
                 ):
                     self._finish_failed_running_turn(
                         "listener recovered without an active Codex turn"
                     )
                     return
                 if self.status == AgentStatus.RUNNING:
-                    await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
+                    await self.send(
+                        "[system] Connection was restored after interruption. Continue your work.",
+                        provenance=MessageProvenance(
+                            origin="system", senders=("system",), subtype="runtime_reconnect",
+                        ),
+                        retry_generation=generation,
+                    )
                 continue
             except Exception as re_err:
                 logger.error(f"[{self.name}] listener reconnect failed: {err_text(re_err)}")
                 self._log("error", f"listener reconnect failed: {err_text(re_err)}")
+                if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                    continue
                 self._backend = None
                 self._finish_failed_running_turn(
                     f"listener reconnect failed: {err_text(re_err)}"
                 )
                 return
 
     async def _turn_event_loop(self) -> None:
         logger.info(f"[{self.name}] {self.backend_type} turn started")
@@ -3214,45 +3227,47 @@ class AgentSession:
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
+    def _finish_failed_continuation(self, generation: tuple[int, int]) -> bool:
+        """An old automatic attempt cannot finish a newer or manually stopped turn."""
+        if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            return False
+        self.status = AgentStatus.IDLE
+        self._persist()
+        self._turns.publish_turn_finished()
+        return True
+
     async def _rate_limit_retry(self, delay: int, expected_turn_gen: int) -> None:
         generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         if self._manually_interrupted or self._turn_gen != expected_turn_gen:
             return
         try:
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="rate_limit_retry",
             )
             await self.send(
                 "[system] Retrying after rate limit. Continue where you left off.",
                 provenance=provenance,
                 retry_generation=generation,
             )
         except DrainingRefused as refusal:
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            if not self._finish_failed_continuation(generation):
                 return
             self._log("status", f"drain: {refusal}")
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
             self._queue_drain_fact("rate-limit-retry", "повтор после rate limit срезан")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
-                return
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
+            self._finish_failed_continuation(generation)
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
         generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         try:
             async with self._lifecycle_lock:
                 # A real user message already started a newer turn; it supersedes this
@@ -3269,57 +3284,50 @@ class AgentSession:
             await self.send(
                 "[system] Retrying after transient server error. Continue where you "
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now.",
                 provenance=provenance,
                 retry_generation=generation,
             )
         except DrainingRefused as refusal:
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+            if not self._finish_failed_continuation(generation):
                 return
             self._log("status", f"drain: {refusal}")
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
             self._queue_drain_fact(
                 "server-error-retry", "повтор после сбоя апстрима срезан",
             )
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
-            if generation != (self._turn_gen, self._turn_start_cancel_gen):
-                return
-            self.status = AgentStatus.IDLE
-            self._persist()
-            self._turns.publish_turn_finished()
+            self._finish_failed_continuation(generation)
 
-    async def _auto_continue(self) -> None:
+    async def _auto_continue(self, expected_turn_gen: int) -> None:
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(1)
+        if self._manually_interrupted or self._turn_gen != expected_turn_gen:
+            return
         try: