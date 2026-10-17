# Candidate cand-05

## ORIGIN commit cc0b4739e2 (2026-06-01): #42: #42: fix P2 bugs — reconnect backoff, hibernate guard, GC task refs, log retention, rawMaxTokens, dead code cleanup
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend.py b/app/backend.py
deleted file mode 100644
index 7dd5491e1..000000000
--- a/app/backend.py
+++ /dev/null
@@ -1,17 +0,0 @@
-"""AgentBackend protocol — abstract interface for Claude/Codex/etc."""
-
-from typing import AsyncIterator, Optional, Protocol, runtime_checkable
-
-from app.events import AgentEvent
-
-
-@runtime_checkable
-class AgentBackend(Protocol):
-    async def connect(self) -> None: ...
-    async def send(self, message: str) -> None: ...
-    def events(self) -> AsyncIterator[AgentEvent]: ...
-    async def interrupt(self) -> None: ...
-    async def disconnect(self) -> None: ...
-
-    @property
-    def session_id(self) -> Optional[str]: ...
diff --git a/app/backend_claude.py b/app/backend_claude.py
index 74231837e..139e32c45 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -174,16 +174,17 @@ class ClaudeBackend:
         if not self._client:
             return None
         try:
             u = await asyncio.wait_for(self._client.get_context_usage(), timeout=5)
             return {
                 "percentage": int(u.get("percentage", 0)),
                 "total_tokens": u.get("totalTokens", 0),
                 "max_tokens": u.get("maxTokens", 0),
+                "raw_max_tokens": u.get("rawMaxTokens", 0),
                 "auto_compact": u.get("isAutoCompactEnabled", False),
                 "auto_compact_threshold": u.get("autoCompactThreshold", 0),
             }
         except asyncio.TimeoutError:
             return None
         except Exception as e:
             logger.debug(f"get_context_usage failed: {e}")
             return None
diff --git a/app/db.py b/app/db.py
index 28cc9580f..b5ddf41d2 100644
--- a/app/db.py
+++ b/app/db.py
@@ -631,50 +631,24 @@ def get_stats(scope: str | None = None) -> dict:
             "total_logs": total_logs,
             "total_turns": agg[0],
             "total_input_tokens": agg[1],
             "total_output_tokens": agg[2],
             "total_tool_calls": agg[3],
         }
 
 
-def get_orchestrators() -> list[dict]:
+def cleanup_old_logs(days: int = 7) -> int:
     with _conn() as c:
-        rows = c.execute(
-            "SELECT * FROM sessions WHERE (is_orchestrator = 1 OR role IN ('orchestrator', 'sub-orchestrator')) "
-            "AND status IN ('starting', 'running', 'idle')"
-        ).fetchall()
-        return [dict(r) for r in rows]
-
-
-def get_resumable_orchestrators() -> list[dict]:
+        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
+        cur = c.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
+        deleted = cur.rowcount
     with _conn() as c:
-        rows = c.execute(
-            "SELECT * FROM sessions WHERE (is_orchestrator = 1 OR role IN ('orchestrator', 'sub-orchestrator')) "
-            "AND session_id IS NOT NULL AND status IN ('running', 'idle')"
-        ).fetchall()
-        return [dict(r) for r in rows]
-
-
-def mark_stale_sessions(exclude_ids: list[str]) -> int:
-    with _conn() as c:
-        if exclude_ids:
-            placeholders = ",".join("?" * len(exclude_ids))
-            cur = c.execute(
-                f"UPDATE sessions SET status = 'error' "
-                f"WHERE status = 'running' AND is_orchestrator = 0 "
-                f"AND id NOT IN ({placeholders})",
-                exclude_ids,
-            )
-        else:
-            cur = c.execute(
-                "UPDATE sessions SET status = 'error' "
-                "WHERE status = 'running' AND is_orchestrator = 0"
-            )
-        return cur.rowcount
+        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
+    return deleted
 
 
 def add_inbox(session_id: str, sender: str, message: str) -> int:
     with _conn() as c:
         cur = c.execute(
             "INSERT INTO inbox (session_id, sender, message, created_at) VALUES (?, ?, ?, ?)",
             (session_id, sender, message, datetime.now(timezone.utc).isoformat()),
         )
diff --git a/app/main.py b/app/main.py
index af0a37626..24ae32737 100644
--- a/app/main.py
+++ b/app/main.py
@@ -30,17 +30,17 @@ manager = SessionManager()
 templates = Jinja2Templates(directory="app/templates")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    await manager.auto_resume_orchestrators()
+    await manager.auto_resume_all()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
     from app.ssh_tunnel import start_tunnel, stop_tunnel
     await start_tunnel()
diff --git a/app/manager.py b/app/manager.py
index 27c0000c1..9dcd1f01f 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -335,16 +335,18 @@ class SessionManager:
     def get_session_lock(self, session_id: str) -> asyncio.Lock:
         if session_id not in self._session_locks:
             self._session_locks[session_id] = asyncio.Lock()
         return self._session_locks[session_id]
 
     def start_background_tasks(self) -> None:
         if not self._spawn_task or self._spawn_task.done():
             self._spawn_task = asyncio.create_task(self._spawn_worker_loop())
+        if not getattr(self, '_cleanup_task', None) or self._cleanup_task.done():
+            self._cleanup_task = asyncio.create_task(self._periodic_db_cleanup())
 
     async def enqueue_worker_spawn(self, **job) -> None:
         await self._spawn_queue.put(job)
 
     async def _spawn_worker_loop(self) -> None:
         from app.db import update_job
         while True:
             job = await self._spawn_queue.get()
@@ -931,18 +933,31 @@ class SessionManager:
             await session.send(
                 "[system] Orchestra server restarted. "
                 "Your session was restored — continue where you left off."
             )
             logger.info(f"Restart notice injected: {session.name}")
         except Exception as e:
             logger.warning(f"Failed to inject restart notice to {session.name}: {e}")
 
-    async def auto_resume_orchestrators(self) -> None:
-        await self.auto_resume_all()
+    async def _periodic_db_cleanup(self) -> None:
+        CLEANUP_INTERVAL = 6 * 3600
+        while True:
+            try:
+                await asyncio.sleep(CLEANUP_INTERVAL)
+                from app.db import cleanup_old_logs
+                deleted = await asyncio.to_thread(cleanup_old_logs, 7)
+                if deleted:
+                    logger.info(f"DB cleanup: deleted {deleted} old log entries")
+            except asyncio.CancelledError:
+                return
+            except Exception as e:
+                logger.warning(f"DB cleanup failed: {e}")
 
     async def shutdown_all(self) -> None:
+        if getattr(self, '_cleanup_task', None) and not self._cleanup_task.done():
+            self._cleanup_task.cancel()
         for session in list(self.sessions.values()):
             try:
                 await session.stop()
             except Exception:
                 pass
         self.sessions.clear()
diff --git a/app/session.py b/app/session.py
index eb94ef66c..0c726b708 100644
--- a/app/session.py
+++ b/app/session.py
@@ -104,16 +104,17 @@ class AgentSession:
     total_turns: int = 0
     total_input_tokens: int = 0
     total_output_tokens: int = 0
     total_tool_calls: int = 0
 
     _backend: Optional[object] = field(default=None, repr=False)
     _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
+    _background_tasks: set = field(default_factory=set, repr=False)
     _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
     _did_report: bool = field(default=False, repr=False)
     _turn_logs: list = field(default_factory=list, repr=False)
     _prompt_injected: bool = field(default=False, repr=False)
     _current_prompt: str = field(default="", repr=False)
     _template_hash: str = field(default="", repr=False)
     _turn_start: float = field(default=0.0, repr=False)
     _last_msg_time: float = field(default=0.0, repr=False)
@@ -159,20 +160,30 @@ class AgentSession:
                 system_prompt=self.system_prompt,
                 resume_session_id=resume,
                 mcp_servers=self.mcp_servers,
                 is_orchestrator=self.is_orchestrator,
                 scope_mcp_servers=_load_scope_mcp_servers(self.scope),
             )
 
     def _codex_reasoning_effort(self) -> str:
-        if self.is_orchestrator:
-            return "high"
         return "high"
 
+    def _spawn_bg(self, coro) -> asyncio.Task:
+        task = asyncio.create_task(coro)
+        self._background_tasks.add(task)
+        def _on_done(t):
+            self._background_tasks.discard(t)
+            if not t.cancelled():
+                exc = t.exception()
+                if exc:
+                    logger.warning(f"[{self.name}] background task failed: {exc}")
+        task.add_done_callback(_on_done)
+        return task
+
     def _build_codex_mcp_env(self) -> dict[str, str]:
         env = {}
         for _name, cfg in self.mcp_servers.items():
             for k, v in cfg.get("env", {}).items():
                 env[k] = str(v)
         return env
 
     async def start(self, initial_message: str | None = None) -> None:
@@ -276,59 +287,79 @@ class AgentSession:
             self._listen_task = asyncio.create_task(self._claude_event_loop())
             self._listen_task.add_done_callback(self._on_task_done)
         if self._heartbeat_task is None or self._heartbeat_task.done():
             self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
         return self._backend
 
     # ── Event loops ──
 
+    MAX_CONSECUTIVE_FAILURES = 5
+
     async def _claude_event_loop(self) -> None:
         logger.info(f"[{self.name}] claude event loop started")
+        consecutive_failures = 0
         while True:
             try:
                 if self._backend is None:
                     logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                     return
                 async for event in self._backend.events():
                     self._last_msg_time = asyncio.get_event_loop().time()
                     if self._turn_start and (asyncio.get_event_loop().time() - self._turn_start) > self.TURN_TIMEOUT:
                         logger.error(f"[{self.name}] turn timeout")
                         self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
                         self._turn_start = 0
                         self.status = AgentStatus.IDLE
                         self._persist()
                         await self._backend.send("[system] Turn timed out. Continue where you left off.")
                         continue
                     self._handle_event(event)
+                    consecutive_failures = 0
+                # events() exhausted normally — treat as failure
+                consecutive_failures += 1
+                logger.warning(f"[{self.name}] events() exhausted normally (attempt {consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES})")
+                self._log("error", f"listener stream ended unexpectedly (attempt {consecutive_failures})")
             except asyncio.CancelledError:
                 logger.info(f"[{self.name}] claude event loop cancelled")
                 return
             except Exception as e:
+                consecutive_failures += 1
                 import traceback
                 tb = traceback.format_exc()
                 logger.error(f"[{self.name}] claude event loop died: {e}\n{tb}")
-                self._log("error", f"listener died (reconnecting): {e}")
-                try:
-                    if self._backend is None:
-                        return
-                    await self._backend.reconnect()
-                    logger.info(f"[{self.name}] listener reconnected after error")
-                    self._log("status", "listener reconnected")
-                    if self.status == AgentStatus.RUNNING:
-                        await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
-                    continue
-                except Exception as re_err:
-                    logger.error(f"[{self.name}] listener reconnect failed: {re_err}")
-                    self._log("error", f"listener reconnect failed: {re_err}")
-                    self._backend = None
-                    if self.status == AgentStatus.RUNNING:
-                        self.status = AgentStatus.IDLE
-                        self._persist()
+                self._log("error", f"listener died (attempt {consecutive_failures}): {e}")
+
+            if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
+                logger.error(f"[{self.name}] reconnect limit reached ({consecutive_failures} consecutive failures), giving up")
+                self._log("error", f"backend unstable: {consecutive_failures} consecutive failures, giving up")
+                self._turn_start = 0
+                await self._disconnect_backend()
+                if self.status == AgentStatus.RUNNING:
+                    self.status = AgentStatus.IDLE
+                    self._persist()
+                return
+
+            try:
+                if self._backend is None:
                     return
+                await self._backend.reconnect()
+                logger.info(f"[{self.name}] listener reconnected after error")
+                self._log("status", "listener reconnected")
+                if self.status == AgentStatus.RUNNING:
+                    await self._backend.send("[system] Connection was restored after interruption. Continue your work.")
+                continue
+            except Exception as re_err:
+                logger.error(f"[{self.name}] listener reconnect failed: {re_err}")
+                self._log("error", f"listener reconnect failed: {re_err}")
+                self._backend = None
+                if self.status == AgentStatus.RUNNING:
+                    self.status = AgentStatus.IDLE
+                    self._persist()
+                return
 
     CODEX_TURN_TIMEOUT = 600
 
     async def _codex_turn_loop(self) -> None:
         logger.info(f"[{self.name}] codex turn started")
         try:
             async with asyncio.timeout(self.CODEX_TURN_TIMEOUT):
                 async for event in self._backend.events():
@@ -343,17 +374,17 @@ class AgentSession:
         except Exception as e:
             logger.error(f"[{self.name}] codex turn error: {e}")
             self._log("error", f"codex turn error: {e}")
         finally:
             if self.status == AgentStatus.RUNNING:
                 self.status = AgentStatus.IDLE
                 self._persist()
                 if self._pending_messages:
-                    asyncio.create_task(self._flush_pending())
+                    self._spawn_bg(self._flush_pending())
                 else:
                     self._schedule_hibernate()
 
     # ── Unified event handler ──
 
     def _handle_event(self, event: AgentEvent) -> None:
         if event.type == "text":
             self._log("text", event.content)
@@ -449,26 +480,26 @@ class AgentSession:
         if ctx_pct:
             self._last_context["percentage"] = ctx_pct
             self._last_context["total_tokens"] = ctx_tokens
         self._last_context["max_tokens"] = meta.get("max_tokens", 200000)
         self._last_context["cache_hit"] = meta.get("cache_hit", 0)
         self._last_context["cache_read"] = meta.get("cache_read", 0)
         self._last_context["cache_create"] = meta.get("cache_create", 0)
 
-        asyncio.create_task(self._refresh_context_from_api())
+        self._spawn_bg(self._refresh_context_from_api())
 
         if not ok:
             errors = meta.get("errors") or []
             err_txt = "; ".join(str(e) for e in errors) if errors else sr
             self._log("error", f"turn FAILED: {err_txt}")
 
         if sr in ("error_max_turns", "max_turns") and ok:
             self._log("status", f"max_turns reached ({nt}), auto-continuing")
-            asyncio.create_task(self._auto_continue())
+            self._spawn_bg(self._auto_continue())
             return
 
         cost = meta.get("cost_usd", 0)
         live_pct = self._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         self._log("status", f"turn ended ({sr}, {nt} turns, ${cost:.2f} {ctx_s})")
 
         from app.bg_jobs import bg_manager
@@ -477,27 +508,26 @@ class AgentSession:
             self._log("status", "waiting for bg jobs")
         else:
             self.status = AgentStatus.IDLE
         self._persist()
 
         if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
             self._compact_ack_event.set()
 
-        asyncio.create_task(self._notify_scope_idle())
+        self._spawn_bg(self._notify_scope_idle())
 
         if live_pct > 90 and not self.is_orchestrator and not self._compacting:
             self._log("status", f"auto-compact triggered ({live_pct}%)")
-            asyncio.create_task(self._auto_compact())
-
+            self._spawn_bg(self._auto_compact())
 
         self._fire_auto_report()
 
         if self._pending_messages:
-            asyncio.create_task(self._flush_pending())
+            self._spawn_bg(self._flush_pending())
             return
 
         self._schedule_hibernate()
 
     async def _flush_pending(self) -> None:
         await asyncio.sleep(0.3)
         if self._compacting:
             return
@@ -547,39 +577,42 @@ class AgentSession:
     async def _idle_hibernate(self, timeout: float) -> None:
         try:
             await asyncio.sleep(timeout)
         except asyncio.CancelledError:
             return
         async with self._lifecycle_lock:
             if self.status != AgentStatus.IDLE:
                 return
+            if self._pending_messages:
+                return
             if self._backend is None:
                 return
             logger.info(f"[{self.name}] hibernating (idle {int(timeout)}s)")
             await self._disconnect_backend()
             self._hibernated = True
 
-
     def _on_task_done(self, task: asyncio.Task) -> None:
         try:
             exc = task.exception()
         except asyncio.CancelledError:
             return
         if exc:
             import traceback
             tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
             logger.error(f"[{self.name}] listen task died with exception: {exc}\n{tb}")
+            self._turn_start = 0
             self.status = AgentStatus.IDLE
             self._log("error", f"listen task exception: {exc}")
             self._persist()
         else:
             logger.warning(f"[{self.name}] listen task exited without exception (silent death), status={self.status}")
             if self.status == AgentStatus.RUNNING:
                 self._log("error", "listen task exited unexpectedly while RUNNING")
+                self._turn_start = 0
                 self.status = AgentStatus.IDLE
                 self._persist()
 
     ZOMBIE_TIMEOUT_CODEX = 600
     ZOMBIE_TIMEOUT_CLAUDE = 1800
 
     async def _heartbeat_loop(self) -> None:
         HEARTBEAT_INTERVAL = 60
@@ -595,17 +628,17 @@ class AgentSession:
                         if self.backend_type == "codex" or self._backend is None:
                             logger.error(f"[{self.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend={'alive' if self._backend else 'dead'})")
                             self._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                             if self._backend:
                                 await self._disconnect_backend()
                             self.status = AgentStatus.IDLE
                             self._persist()
                             if self._pending_messages:
-                                asyncio.create_task(self._flush_pending())
+                                self._spawn_bg(self._flush_pending())
                         else:
                             logger.warning(f"[{self.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                             self._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")
 
                 if self._backend is None:
                     continue
 
                 task_dead = self._listen_task is None or self._listen_task.done()
@@ -724,17 +757,17 @@ class AgentSession:
                 self.status = AgentStatus.IDLE
                 self._persist()
                 return {"ok": False, "error": "ack turn did not complete", "before_pct": before_pct}
         finally:
             self._compact_ack_event = None
             self._compact_ack_gen = -1
             self._compacting = False
             if self._pending_messages:
-                asyncio.create_task(self._flush_pending())
+                self._spawn_bg(self._flush_pending())
 
         after_pct = self._last_context.get("percentage", 0)
         self._log("status", f"compact done: {before_pct}% → {after_pct}%")
         return {"ok": True, "before_pct": before_pct, "after_pct": after_pct, "summary_chars": len(summary), "summary": summary}
 
     async def _notify_scope_idle(self) -> None:
         try:
             from app.tg_bridge import check_scope_idle, _manager as tg_mgr
@@ -767,18 +800,19 @@ class AgentSession:
         if not self._backend or not hasattr(self._backend, 'context_usage'):
             return
         try:
             usage = await asyncio.wait_for(self._backend.context_usage(), timeout=5)
             if usage and usage.get("percentage") is not None:
                 old_pct = self._last_context.get("percentage", 0)
                 self._last_context["percentage"] = usage["percentage"]
                 self._last_context["total_tokens"] = usage.get("total_tokens", 0)
-                if usage.get("max_tokens"):
-                    self._last_context["max_tokens"] = usage["max_tokens"]
+                raw_max = usage.get("raw_max_tokens") or usage.get("max_tokens")
+                if raw_max:
+                    self._last_context["max_tokens"] = raw_max
                 if abs(old_pct - usage["percentage"]) > 30:
                     logger.info(f"[{self.name}] context corrected: {old_pct}% → {usage['percentage']}%")
                 self._persist()
         except asyncio.TimeoutError:
             logger.debug(f"[{self.name}] context refresh timeout (5s)")
         except Exception as e:
             logger.debug(f"[{self.name}] context refresh failed: {e}")
 
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index ac11fc6ac..e534f2107 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -368,51 +368,32 @@ async def _resolve_media(sid: str, idx: int, content: str):
             if buf.debounce_task and not buf.debounce_task.done():
                 buf.debounce_task.cancel()
             buf.debounce_task = None
             flush_batch = batch
     if flush_batch is not None:
         await _flush_batch(sid, flush_batch)
 
 
-async def _react_processing(msg: types.Message):
-    pass
 
 
 def _utf16_len(s: str) -> int:
     return len(s.encode("utf-16-le")) // 2
 
 
 def _md_entities(text: str, base_offset: int = 0):
     from aiogram.types import MessageEntity as AioEntity
     try:
         converted, raw_ents = md_convert(text)
         ents = [AioEntity(**{**e.to_dict(), "offset": e.offset + base_offset}) for e in raw_ents] if raw_ents else []
         return converted, ents
     except Exception:
         return text, []
 
 
-async def _send_expandable_return(chat_id: int, thread_id: int, header: str, body: str):
-    from aiogram.types import MessageEntity
-    from aiogram.enums import MessageEntityType
-    body = body.rstrip()
-    conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
-    text = f"{header}\n{conv_body}"
-    offset = _utf16_len(header) + 1
-    length = _utf16_len(conv_body)
-    try:
-        entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
-        return await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
-    except Exception:
-        try:
-            return await bot.send_message(chat_id, text, message_thread_id=thread_id)
-        except Exception as e:
-            logger.warning(f"TG send failed: {e}")
-            return None
 
 
 async def _edit_tool_with_result(msg, chat_id: int, tool_text: str, result_header: str, result_body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     nl = tool_text.index("\n")
     tool_header = tool_text[:nl]
     tool_body = tool_text[nl + 1:].rstrip()
@@ -464,28 +445,30 @@ async def _edit_expandable(msg, chat_id: int, header: str, body: str):
         except Exception as e2:
             if "message is not modified" not in str(e2).lower():
                 logger.warning(f"TG edit failed: {e2}")
 
 
 async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
+    body = body.rstrip()
     conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
     text = f"{header}\n{conv_body}"
     offset = _utf16_len(header) + 1
     length = _utf16_len(conv_body)
     try:
         entities = [MessageEntity(type=MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=offset, length=length)] + body_ents
-        await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
+        return await bot.send_message(chat_id, text, message_thread_id=thread_id, entities=entities)
     except Exception:
         try:
-            await bot.send_message(chat_id, text, message_thread_id=thread_id)
+            return await bot.send_message(chat_id, text, message_thread_id=thread_id)
         except Exception as e:
             logger.warning(f"TG send failed: {e}")
+            return None
 
 
 TG_MSG_LIMIT = 4096
 
 
 def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
     if len(text) <= limit:
         return [text]
@@ -930,17 +913,17 @@ async def stream_logs(orch_name: str, thread_id: int):
                         text = f"{head}\n{c}"
                     elif t == "tool":
                         tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                         tool_body = c[len(tool_name)+1:].strip()[:1200] if ":" in c else c[:1200]
                         icon = _tg_tool_icon(tool_name)
                         short = _tg_tool_short(tool_name)
                         header = f"{icon} {short}"
                         _last_tool_text = f"{header}\n{tool_body}"
-                        _last_tool_msg = await _send_expandable_return(config["group_id"], thread_id, header, tool_body)
+                        _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                         try:
                             m_text, m_ents = md_convert(f"{header}\n{tool_body}")
                             from aiogram.types import MessageEntity as AioEntity
                             await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                         except Exception:
                             await _mirror_send(orch_name, f"{header}\n{tool_body}")
                         continue
                     elif t == "tool_result":
@@ -949,17 +932,17 @@ async def stream_logs(orch_name: str, thread_id: int):
                         if _last_tool_msg:
                             await _edit_tool_with_result(
                                 _last_tool_msg, config["group_id"],
                                 _last_tool_text, f"📎 {result_preview}", result_body,
                             )
                             _last_tool_msg = None
                             _last_tool_text = ""
                         else:
-                            await _send_expandable_return(config["group_id"], thread_id, f"📎 {result_preview}", result_body)
+                            await _send_expandable(config["group_id"], thread_id, f"📎 {result_preview}", result_body)
                         try:
                             m_text, m_ents = md_convert(f"📎 {result_preview}\n{result_body}")
                             from aiogram.types import MessageEntity as AioEntity
                             await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                         except Exception:
                             await _mirror_send(orch_name, f"📎 {result_preview}\n{result_body}")
                         continue
                     elif t == "error":
@@ -1001,17 +984,17 @@ async def handle_restart(msg: types.Message):
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.voice)
 async def handle_voice(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
     t_total = time.monotonic()
-    await _react_processing(msg)
+
     sid, idx = await _register_media(msg, session)
     path = await _download_file(msg.voice.file_id, _media_name("voice", ".oga", msg), msg.voice.file_unique_id)
     tag = _sender_tag(msg)
     if not path:
         await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: file too large]")
         return
     text, err = await _transcribe_audio(path, msg.voice.file_unique_id)
     total_ms = (time.monotonic() - t_total) * 1000
@@ -1024,17 +1007,17 @@ async def handle_voice(msg: types.Message):
         await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[voice: {path}]")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.video_note)
 async def handle_video_note(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
-    await _react_processing(msg)
+
     sid, idx = await _register_media(msg, session)
     tag = _sender_tag(msg)
     path = await _download_file(msg.video_note.file_id, _media_name("videonote", ".mp4", msg), msg.video_note.file_unique_id)
     if not path:
         await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: file too large]")
         return
     audio_path = path.replace(".mp4", ".oga")
     p = await asyncio.create_subprocess_exec(
@@ -1053,55 +1036,55 @@ async def handle_video_note(msg: types.Message):
     await _resolve_media(sid, idx, f"{tag}{_forward_meta(msg)}[video_note: {path}]")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
 async def handle_photo(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
-    await _react_processing(msg)
+
     path = await _download_file(msg.photo[-1].file_id, _media_name("photo", ".jpg", msg), msg.photo[-1].file_unique_id)
     caption = f"\n{msg.caption}" if msg.caption else ""
     tag = f"[photo: {path}]" if path else "[photo: file too large]"
     await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.document)
 async def handle_document(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
-    await _react_processing(msg)
+
     doc = msg.document
     ext = os.path.splitext(doc.file_name or "file")[1] or ".bin"
     path = await _download_file(doc.file_id, doc.file_name or _media_name("doc", ext, msg), doc.file_unique_id)
     caption = f"\n{msg.caption}" if msg.caption else ""
     tag = f"[file: {path} | {doc.file_name}]" if path else f"[file: too large | {doc.file_name}]"
     await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.video)
 async def handle_video(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
-    await _react_processing(msg)
+
     path = await _download_file(msg.video.file_id, msg.video.file_name or _media_name("video", ".mp4", msg), msg.video.file_unique_id)
     caption = f"\n{msg.caption}" if msg.caption else ""
     tag = f"[video: {path}]" if path else "[video: file too large]"
     await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.audio)
 async def handle_audio(msg: types.Message):
     orch_name, session = await _resolve_orch(msg)
     if not session:
         return
-    await _react_processing(msg)
+
     name = msg.audio.file_name or _media_name("audio", ".mp3", msg)
     path = await _download_file(msg.audio.file_id, name, msg.audio.file_unique_id)
     caption = f"\n{msg.caption}" if msg.caption else ""
     tag = f"[audio: {path} | {name}]" if path else f"[audio: too large | {name}]"
     await _send_to_agent(msg, session, f"{_forward_meta(msg)}{tag}{caption}")
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.sticker)
diff --git a/app/workspace.py b/app/workspace.py
index 19c40b981..588d687ae 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -155,20 +155,16 @@ def _ensure_repo_on_branch(repo: str, target_branch: str = "main") -> tuple[str
             ["git", "checkout", target_branch], cwd=repo, capture_output=True, text=True,
         )
         if checkout.returncode != 0:
             # НЕ делаем stash pop здесь — did_stash=True сигнализирует finally в вызывающем коде
             return f"cannot checkout {target_branch} in repo: {checkout.stderr.strip()}", did_stash
     return None, did_stash
 
 
-# Алиас для обратной совместимости
-_ensure_repo_on_main = _ensure_repo_on_branch
-
-
 def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
     """Return subject lines of commits in branch not in base."""
     log = subprocess.run(
         ["git", "log", f"{base}..{branch}", "--format=%s", "--reverse"],
         cwd=repo, capture_output=True, text=True,
     )
     if log.returncode != 0 or not log.stdout.strip():
         return []
diff --git a/tests/test_db.py b/tests/test_db.py
index db7f83a2e..ab7885bf5 100644
--- a/tests/test_db.py
+++ b/tests/test_db.py
@@ -221,99 +221,16 @@ class TestLogs:
         sid = sample_session["id"]
         for t in ("text", "tool", "error", "status", "user_message", "notification"):
             add_log(sid, datetime.now(timezone.utc), t, f"type-{t}")
         logs = get_logs(sid)
         types = {l["type"] for l in logs}
         assert types == {"text", "tool", "error", "status", "user_message", "notification"}
 
 
-class TestOrchestrators:
-    def test_returns_only_orchestrators(self, db, sample_session):
-        from app.db import save_session, get_orchestrators
-        save_session(sample_session)
-        orch = {
-            **sample_session,
-            "id": "orch-uuid",
-            "name": "orchestrator",
-            "is_orchestrator": True,
-            "session_id": "sdk-session-123",
-            "status": "idle",
-        }
-        save_session(orch)
-        result = get_orchestrators()
-        assert len(result) == 1
-        assert result[0]["name"] == "orchestrator"
-
-    def test_excludes_stopped(self, db, sample_session):
-        from app.db import save_session, get_orchestrators
-        orch = {
-            **sample_session,
-            "id": "orch-uuid",
-            "name": "orchestrator",
-            "is_orchestrator": True,
-            "session_id": "sdk-session-123",
-            "status": "stopped",
-        }
-        save_session(orch)
-        assert len(get_orchestrators()) == 0
-
-    def test_includes_no_session_id(self, db, sample_session):
-        from app.db import save_session, get_orchestrators
-        orch = {
-            **sample_session,
-            "id": "orch-uuid",
-            "name": "orchestrator",
-            "is_orchestrator": True,
-            "session_id": None,
-            "status": "idle",
-        }
-        save_session(orch)
-        assert len(get_orchestrators()) == 1
-
-    def test_resumable_excludes_no_session_id(self, db, sample_session):
-        from app.db import save_session, get_resumable_orchestrators
-        orch = {
-            **sample_session,
-            "id": "orch-uuid",
-            "name": "orchestrator",
-            "is_orchestrator": True,
-            "session_id": None,
-            "status": "idle",
-        }
-        save_session(orch)
-        assert len(get_resumable_orchestrators()) == 0
-
-
-class TestMarkStaleSessions:
-    def test_marks_running_non_orchestrators(self, db, sample_session):
-        from app.db import save_session, mark_stale_sessions, get_session
-        running = {**sample_session, "status": "running"}
-        save_session(running)
-        count = mark_stale_sessions(exclude_ids=[])
-        assert count == 1
-        got = get_session(sample_session["id"])
-        assert got["status"] == "error"
-
-    def test_excludes_given_ids(self, db, sample_session):
-        from app.db import save_session, mark_stale_sessions, get_session
-        running = {**sample_session, "status": "running"}
-        save_session(running)
-        count = mark_stale_sessions(exclude_ids=[sample_session["id"]])
-        assert count == 0
-        assert get_session(sample_session["id"])["status"] == "running"
-
-    def test_skips_orchestrators(self, db, sample_session):
-        from app.db import save_session, mark_stale_sessions, get_session
-        orch = {**sample_session, "status": "running", "is_orchestrator": True}
-        save_session(orch)
-        count = mark_stale_sessions(exclude_ids=[])
-        assert count == 0
-
-
 class TestStats:
     def test_aggregation(self, db, sample_session):
         from app.db import save_session, get_stats, add_log
         s1 = {**sample_session, "status": "running", "cost_usd": 0.5}
         save_session(s1)
         s2 = {
             **sample_session,
             "id": "s2-uuid",
diff --git a/tests/test_disallowed_tools.py b/tests/test_disallowed_tools.py
index 7c5be6ec4..473460a16 100644
--- a/tests/test_disallowed_tools.py
+++ b/tests/test_disallowed_tools.py
@@ -4,9 +4,11 @@ from app.backend_claude import _disallowed_tools
 
 
 def test_orchestrator_disallows_subagent_tool():
     d = _disallowed_tools(True)
     assert "Task" in d and "Agent" in d
 
 
 def test_worker_keeps_subagent_tool():
-    assert _disallowed_tools(False) == []
+    d = _disallowed_tools(False)
+    assert "Task" not in d and "Agent" not in d
+    assert "ScheduleWakeup" in d
diff --git a/tests/test_manager.py b/tests/test_manager.py
index 35ec9d563..e12bc96bb 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -242,17 +242,17 @@ class TestAutoResume:
             "cwd": "/tmp", "model": "claude-opus-4-6", "system_prompt": "",
             "status": "idle", "session_id": "sdk-123",
             "cost_usd": 0.0, "worktree_path": None, "branch": None,
             "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
             "finished_at": None,
         })
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
-            await mgr.auto_resume_orchestrators()
+            await mgr.auto_resume_all()
         assert mgr.get("orch-1") is not None
 
 
 
 class TestCanSpawn:
     def _write_role(self, roles_dir, name, frontmatter_body):
         (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter_body}\n---\n\nBody for {name}.\n")
 


## LATER FIX d9b5bc3c3c (62.9 days later): fix: не удалять логи агентов никогда — убран таймер retention, cleanup_old_logs падает при вызове
lines of origin it changed/deleted: 20
(code only, capped 400 lines)

fix: не удалять логи агентов никогда — убран таймер retention, cleanup_old_logs падает при вызове


diff --git a/app/db.py b/app/db.py
index 5d2df10fa..fcb3181a7 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1062,25 +1062,26 @@ def get_stats(scope: str | None = None) -> dict:
             "total_turns": agg[0],
             "total_input_tokens": agg[1],
             "total_output_tokens": agg[2],
             "total_tool_calls": agg[3],
         }
 
 
 def cleanup_old_logs(days: int = 7) -> int:
-    with _conn() as c:
-        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
-        cur = c.execute("DELETE FROM logs WHERE ts < ?", (cutoff,))
-        deleted = cur.rowcount
-    with _conn() as c:
-        # Checkpoint after bulk delete: reclaims WAL disk space that stays
-        # allocated otherwise until the next checkpoint or DB restart
-        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
-    return deleted
+    """REMOVED by owner decision — agent history is research data, never delete it.
+
+    Kept as a loud tombstone: this function used to drop `logs` older than 7 days on a
+    6-hour timer, which silently destroyed every diary older than a week while `sessions`
+    rows survived since May. Any caller is a bug.
+    """
+    raise RuntimeError(
+        "cleanup_old_logs is disabled: agent logs must never be deleted. "
+        "If disk pressure is real, export to files first and ask the owner."
+    )
 
 
 # ── Background Jobs ──
 
 def bg_save_job(job: dict) -> None:
     with _conn() as c:
         c.execute("""
             INSERT INTO bg_jobs (id, type, config, message, target_session_id,
diff --git a/app/manager.py b/app/manager.py
index dc1905dfa..9ee518c9b 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -334,18 +334,19 @@ class SessionManager:
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
 
     def get_session_lock(self, session_id: str) -> asyncio.Lock:
         if session_id not in self._session_locks:
             self._session_locks[session_id] = asyncio.Lock()
         return self._session_locks[session_id]
 
     def start_background_tasks(self) -> None:
-        if not getattr(self, '_cleanup_task', None) or self._cleanup_task.done():
-            self._cleanup_task = asyncio.create_task(self._periodic_db_cleanup())
+        # log retention REMOVED by owner decision: agent history is research data. The old
+        # `_periodic_db_cleanup` dropped logs older than 7 days every 6h, silently destroying
+        # every transcript past a week while `sessions` rows survived since May. Never restore
         if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
             self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())
 
     @staticmethod
     def _ownership_prompt(owned_dirs: list[str]) -> str:
         if not owned_dirs:
             return ""
         lines = "\n".join(f"- {d}/" for d in owned_dirs)
@@ -1512,30 +1513,16 @@ class SessionManager:
                 session.id,
                 "[system] Orchestra server restarted. "
                 "Your session was restored — continue where you left off."
             )
             logger.info(f"Restart notice injected: {session.name}")
         except Exception as e:
             logger.warning(f"Failed to inject restart notice to {session.name}: {e}")
 
-    async def _periodic_db_cleanup(self) -> None:
-        CLEANUP_INTERVAL = 6 * 3600
-        while True:
-            try:
-                await asyncio.sleep(CLEANUP_INTERVAL)
-                from app.db import cleanup_old_logs
-                deleted = await asyncio.to_thread(cleanup_old_logs, 7)
-                if deleted:
-                    logger.info(f"DB cleanup: deleted {deleted} old log entries")
-            except asyncio.CancelledError:
-                return
-            except Exception as e:
-                logger.warning(f"DB cleanup failed: {e}")
-
     async def _periodic_worktree_cleanup(self) -> None:
         WT_CLEANUP_INTERVAL = 24 * 3600
         try:
             from app.workspace import cleanup_stale_worktrees
             removed = await asyncio.to_thread(cleanup_stale_worktrees)
             if removed:
                 logger.info(f"Startup worktree cleanup: removed {len(removed)} stale worktree(s)")
         except Exception as e: