# Candidate cand-52

## ORIGIN commit 11f2e2a02a (2026-07-16): Session 07-11 to 07-16: effort, RAG, Sol, Interaction Tax, worker-spawning, cache pills, TG UTF-16
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/session.py b/app/session.py
index 359368087..43a36fb07 100644
--- a/app/session.py
+++ b/app/session.py
@@ -189,18 +189,18 @@ class AgentSession:
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _persist_dirty: bool = field(default=False, repr=False)
     _turn_gen: int = field(default=0, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
     _auto_continue_count: int = field(default=0, repr=False)
     _rate_limit_retries: int = field(default=0, repr=False)
     _session_limit_hit: bool = field(default=False, repr=False)
+    _manually_interrupted: bool = field(default=False, repr=False)
 
-    TURN_TIMEOUT = 600
     AUTO_CONTINUE_MAX = 5
     RATE_LIMIT_MAX_RETRIES = 3
     RATE_LIMIT_DELAY = 30
 
     def __post_init__(self) -> None:
         # Systems over state (ECS): cost/turn/hibernate methods live in systems,
         # all fields stay on the session (persistence reads them directly)
         self._cost = CostTracker(self)
@@ -384,16 +384,17 @@ class AgentSession:
                 current_th = prompt_template_hash(self.role)
                 old_th = self._template_hash or current_th
                 templates_changed = old_th != current_th
                 pending_th = current_th
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
             if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
+                self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
                 asyncio.create_task(self._notify_scope_running())
@@ -459,23 +460,16 @@ class AgentSession:
         consecutive_failures = 0
         while True:
             try:
                 if self._backend is None:
                     logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                     return
                 async for event in self._backend.events():
                     self._last_msg_time = asyncio.get_event_loop().time()
-                    if self._turn_start and (asyncio.get_event_loop().time() - self._turn_start) > self.TURN_TIMEOUT:
-                        logger.error(f"[{self.name}] turn timeout")
-                        self._log("error", f"Turn timeout ({self.TURN_TIMEOUT}s)")
-                        self._turn_start = asyncio.get_event_loop().time()
-                        # Keep status=RUNNING — agent is actively being continued
-                        await self._backend.send("[system] Turn timed out. Continue where you left off.")
-                        continue
                     self._handle_event(event)
                     consecutive_failures = 0
                 # For opencode: events() finishing = turn done (per-turn generator, not persistent stream).
                 # Exit cleanly — next send() will start a new listen task.
                 if self.backend_type == "opencode":
                     logger.info(f"[{self.name}] opencode turn completed normally, status={self.status}")
                     if self.status == AgentStatus.RUNNING:
                         self.status = AgentStatus.IDLE
@@ -528,29 +522,28 @@ class AgentSession:
                 logger.error(f"[{self.name}] listener reconnect failed: {re_err}")
                 self._log("error", f"listener reconnect failed: {re_err}")
                 self._backend = None
                 if self.status == AgentStatus.RUNNING:
                     self.status = AgentStatus.IDLE
                     self._persist()
                 return
 
-    CODEX_TURN_TIMEOUT = 600
-
     async def _codex_turn_loop(self) -> None:
         logger.info(f"[{self.name}] codex turn started")
         try:
-            async with asyncio.timeout(self.CODEX_TURN_TIMEOUT):
-                async for event in self._backend.events():
-                    self._last_msg_time = asyncio.get_event_loop().time()
-                    self._handle_event(event)
-        except TimeoutError:
-            logger.error(f"[{self.name}] codex turn timed out ({self.CODEX_TURN_TIMEOUT}s)")
-            self._log("error", f"codex turn timed out ({self.CODEX_TURN_TIMEOUT}s), killing backend")
-            await self._disconnect_backend()
+            async for event in self._backend.events():
+                self._last_msg_time = asyncio.get_event_loop().time()
+                # thread.started is emitted before turn.completed. Store it now so an
+                # interrupted long turn can resume instead of silently starting fresh.
+                early_session_id = event.metadata.get("session_id") if event.type == "status" else None
+                if early_session_id and early_session_id != self.session_id:
+                    self.session_id = early_session_id
+                    self._persist()
+                self._handle_event(event)
         except asyncio.CancelledError:
             return
         except Exception as e:
             logger.error(f"[{self.name}] codex turn error: {e}")
             self._log("error", f"codex turn error: {e}")
         finally:
             if self.status == AgentStatus.RUNNING:
                 self.status = AgentStatus.IDLE
@@ -661,16 +654,17 @@ class AgentSession:
             )
         self._log("status", f"delivering {len(msgs)} queued message(s)")
         try:
             async with self._lifecycle_lock:
                 if self._compacting:
                     # compact grabbed the lock first — requeue, compact's finally re-flushes
                     self._pending_messages[0:0] = msgs
                     return
+                self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
                 backend = await self._ensure_backend()
@@ -701,22 +695,33 @@ class AgentSession:
                 self._log("error", "listen task exited unexpectedly while RUNNING")
                 self._turn_start = 0
                 self.status = AgentStatus.IDLE
                 self._persist()
 
     # ── Session operations ──
 
     async def interrupt(self) -> None:
-        if self._backend and self.status == AgentStatus.RUNNING:
-            await self._backend.interrupt()
-        self._turns.cancel_auto_report()
-        self.status = AgentStatus.IDLE
-        self._log("status", "interrupted")
-        self._persist()
+        async with self._lifecycle_lock:
+            backend = self._backend if self.status == AgentStatus.RUNNING else None
+            # Publish the stop before waiting for the SDK control acknowledgement. This
+            # prevents concurrent messages from being injected into the turn being
+            # interrupted; they will start a clean turn after this lock is released.
+            self._turns.cancel_auto_report()
+            self._turn_start = 0
+            self._manually_interrupted = True
+            self.status = AgentStatus.IDLE
+            self._log("status", "interrupted")
+            self._persist()
+
+            if backend:
+                acknowledged = await backend.interrupt()
+                if acknowledged is False and self._backend is backend:
+                    self._log("error", "interrupt was not acknowledged; disconnecting backend")
+                    await self._disconnect_backend()
 
     async def compact(self) -> dict:
         _ORCH_PRESAVE = (
             "BEFORE writing the summary — persist your knowledge to files so it survives compact:\n"
             "1. CLAUDE.md — append key decisions, new rules, patterns discovered this session (section '## Session notes')\n"
             "2. TODO.md — add new items, remove done items\n"
             "3. BUGS.md — add found bugs, close fixed ones\n"
             "4. docs/ — save any research or analysis worth keeping\n"
@@ -831,16 +836,17 @@ class AgentSession:
                 "context_pct": before_pct,
             })
             MAX_HISTORY = 10
             self.session_id_history = self.session_id_history[-MAX_HISTORY:]
         self._compact_ack_event = asyncio.Event()
         ack_event = self._compact_ack_event
         try:
             async with self._lifecycle_lock:
+                self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._compact_ack_gen = self._turn_gen
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
@@ -951,17 +957,18 @@ class AgentSession:
         snapshot = self._to_db_dict()
         await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
         return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}
 
     async def _disconnect_backend(self) -> None:
         if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
             self._hibernate_task.cancel()
             self._hibernate_task = None
-        if self._heartbeat_task and not self._heartbeat_task.done():
+        if (self._heartbeat_task and not self._heartbeat_task.done()
+                and self._heartbeat_task is not asyncio.current_task()):
             self._heartbeat_task.cancel()
             try:
                 await self._heartbeat_task
             except asyncio.CancelledError:
                 pass
             except Exception as e:
                 logger.warning(f"[{self.name}] heartbeat task failed on disconnect: {e}")
             self._heartbeat_task = None
diff --git a/app/session_turns.py b/app/session_turns.py
index 36d6e3451..4b84717b4 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -83,17 +83,17 @@ class TurnManager:
         Orchestrators don't auto-report — they reply to user directly.
         Skipped if worker already sent explicit send_message, has pending messages,
         or was interrupted/stopped by user.
 
         Without this, silent workers (those that don't call send_message) would
         leave the orchestrator waiting forever for a signal that never comes.
         """
         s = self.s
-        if s.is_orchestrator or not s.on_idle or s._did_report:
+        if s.is_orchestrator or not s.on_idle or s._did_report or s._manually_interrupted:
             return
         if s._pending_messages or s._compacting:
             return
         # User wrote to worker directly (no sender = dashboard/TG) → user sees the response,
         # no need to spam the orchestrator with auto-report
         if not s.last_task_sender:
             return
         last_texts = s._turn_logs[-5:] if s._turn_logs else []
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 012310d7d..7b0b7e904 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1480,16 +1480,18 @@ function _renderCachePill(pill) {
 }
 
 // Client-side countdown — re-render all pills every 30s without re-polling
 function _startCacheCountdown() {
     if (window._cacheTimer) return;
     window._cacheTimer = setInterval(() => {
         document.querySelectorAll('.cache-pill[data-cache-expires]').forEach(_renderCachePill);
     }, 30000);
+    // Refresh orch tabs every 60s to pick up new last_turn_ts
+    setInterval(() => loadOrchestrators(), 60000);
 }
 
 function createAgentItem(s) {
     const isSelected = s.name === selectedAgent;
     const isDead = s.status === 'stopped' || s.status === 'error';
     const item = document.createElement('div');
     item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
         isSelected ? 'bg-indigo-900/30 border border-indigo-500/30' :


## LATER FIX 6057d1e11d (80.9 days later): V-706: #V-706: fix session API and delivery lifecycle
lines of origin it changed/deleted: 6
(code only, capped 400 lines)

V-706: #V-706: fix session API and delivery lifecycle

Squashed commits:
- #V-706: fix session API and delivery lifecycle
- #V-706: record committed mutation checks

Orchestra-Operation: aeaa1c31-4486-4f7c-8fe3-3fa549fd8ded


diff --git a/app/limit_wake.py b/app/limit_wake.py
index 9f1d582c8..fc7578ab5 100644
--- a/app/limit_wake.py
+++ b/app/limit_wake.py
@@ -11,17 +11,16 @@ from app.db import (
     bg_finish_trigger,
     bg_get_active_all,
     bg_claim_trigger,
     bg_update_config,
     get_all_sessions,
 )
 from app.errtext import err_text
 from app.events import MessageProvenance
-from app.models import backend_for_model
 from app.session_state import AgentStatus
 
 logger = logging.getLogger(__name__)
 
 WAKE_ACTION = "wake_subscription_limited"
 WAKE_JOB_PREFIX = "wake-limit-"
 WAKE_STAGGER_SECONDS = 30
 MANUAL_ACTION_URL = "https://claude.ai/settings/usage"
@@ -36,24 +35,16 @@ def _is_limit_wake_log(row: dict) -> bool:
     detail = row.get("origin_detail")
     return (
         row.get("origin") == "system"
         and isinstance(detail, dict)
         and detail.get("subtype") == "limit_wake"
     )
 
 
-def _provider_for_model(model: str) -> str:
-    if backend_for_model(model) == "claude":
-        return "anthropic"
-    if model == "gpt-5.3-codex-spark":
-        return "codex_spark"
-    return "codex"
-
-
 def _latest_limit_turn(logs: list[dict]) -> tuple[str, int] | None:
     use_timestamps = all(row.get("ts") for row in logs)
     key = (
         (lambda row: (row["ts"], row["id"]))
         if use_timestamps
         else (lambda row: row["id"])
     )
     ordered = sorted(logs, key=key)
@@ -103,28 +94,36 @@ def _latest_limit_turn(logs: list[dict]) -> tuple[str, int] | None:
     return ("monthly" if monthly else "timed", latest["id"])
 
 
 def find_limit_stopped_agents(
     sessions: list[dict],
     logs_by_session: dict[str, list[dict]],
 ) -> list[dict]:
     """Return idle agents whose most recent completed turn hit a subscription limit."""
+    from app.quota_gate import quota_bucket_for_model
+
     result = []
     for session in sessions:
         if session.get("status") in {"running", "starting", "archived"}:
             continue
+        try:
+            provider = quota_bucket_for_model(session["model"])
+        except ValueError:
+            continue
+        if provider is None:
+            continue
         limit = _latest_limit_turn(logs_by_session.get(session["id"], []))
         if not limit:
             continue
         kind, turn_id = limit
         result.append({
             **session,
             "limit_kind": kind,
-            "provider": _provider_for_model(session["model"]),
+            "provider": provider,
             "limit_turn_id": turn_id,
         })
     return result
 
 
 def _parse_reset(value: object) -> datetime | None:
     if not value:
         return None
diff --git a/app/message_deliveries.py b/app/message_deliveries.py
index 6f159df3e..793fdb376 100644
--- a/app/message_deliveries.py
+++ b/app/message_deliveries.py
@@ -41,45 +41,54 @@ def _payload_hash(**payload: object) -> str:
         {"protocol": "direct-message/v1", **payload},
         ensure_ascii=False,
         sort_keys=True,
         separators=(",", ":"),
     ).encode("utf-8")
     return hashlib.sha256(encoded).hexdigest()
 
 
-def _resource(row: sqlite3.Row | dict, *, acceptance: str = "ACCEPTED") -> dict:
+def _resource(
+    row: sqlite3.Row | dict,
+    *,
+    acceptance: str = "ACCEPTED",
+    connection: sqlite3.Connection | None = None,
+) -> dict:
     error = json.loads(row["error_json"]) if row["error_json"] else None
     provider_ref = row["provider_ref"]
     if isinstance(provider_ref, str) and provider_ref.startswith(_STEERED_PROVIDER_REF_PREFIX):
         provider_ref = provider_ref[len(_STEERED_PROVIDER_REF_PREFIX):]
     stalled = bool(error) and error.get("code") == "TURN_NOT_STARTED"
     return {
         "ok": True,
         "acceptance": acceptance,
         "delivery_id": row["delivery_id"],
         "delivery_state": row["state"],
         "payload_hash": row["payload_hash"],
         "accept_seq": row["accept_seq"],
         "status_url": f"/api/message-deliveries/{row['delivery_id']}",
         "provider_ref": provider_ref,
         "error": error,
-        "next_action": _next_action(row),
+        "next_action": _next_action(row, connection=connection),
         **({"stalled": True} if stalled else {}),
     }
 
 
-def _queue_block(row: sqlite3.Row | dict) -> dict:
+def _queue_block(
+    row: sqlite3.Row | dict,
+    *,
+    connection: sqlite3.Connection | None = None,
+) -> dict:
     """Почему принятое сообщение никуда не поедет: неразобранная голова очереди.
 
     Барьер `DELIVERY_UNKNOWN` намеренный (#380 R7), но молчать про него нельзя:
     отправитель получал бодрый `state=QUEUED` на каждое следующее сообщение, воркер
     выглядел живым и глухим, и так простояли 25 часов и три задания.
     """
-    head = _next_target_delivery(row["target_session_id"])
+    head = _next_target_delivery(row["target_session_id"], connection=connection)
     if (
         head is None
         or head["state"] != "DELIVERY_UNKNOWN"
         or head["delivery_id"] == row["delivery_id"]
     ):
         return {}
     return {
         "code": "TARGET_QUEUE_BLOCKED",
@@ -93,17 +102,21 @@ def _queue_block(row: sqlite3.Row | dict) -> dict:
             "provider outcome is still unknown. Nothing queued after it moves while "
             "that outcome could still change. Do not resend this message: the next "
                 "operator can restart only the target CLI to release the queue; "
                 "the ambiguous message will NOT be resent."
         ),
     }
 
 
-def _next_action(row: sqlite3.Row | dict) -> dict:
+def _next_action(
+    row: sqlite3.Row | dict,
+    *,
+    connection: sqlite3.Connection | None = None,
+) -> dict:
     if row["state"] == "WAITING_NEXT_TURN":
         return {
             "code": "WAITING_NEXT_TURN",
             "retryable": False,
             "message": (
                 "The active turn ended before this message was processed; it is "
                 "durably queued for the target's next turn. Do not resend."
             ),
@@ -115,20 +128,20 @@ def _next_action(row: sqlite3.Row | dict) -> dict:
             "code": "CANCELLED",
             "retryable": False,
             "message": "The sender cancelled this delivery; it was never sent to the target.",
         }
     # Блокировка очереди едет в `next_action`, а не отдельным ключом: это единственное
     # поле receipt'а, которое читают потребители остальных доставок и мержей, — второй
     # носитель той же мысли просто никто бы не открыл.
     if row["state"] == "QUEUED":
-        block = _queue_block(row)
+        block = _queue_block(row, connection=connection)
         if block:
             return block
-        head = _next_target_delivery(row["target_session_id"])
+        head = _next_target_delivery(row["target_session_id"], connection=connection)
         if (
             head is not None
             and head["state"] == "WAITING_QUOTA"
             and head["delivery_id"] != row["delivery_id"]
         ):
             return {
                 "code": "BEHIND_QUOTA_WAIT",
                 "retryable": False,
@@ -280,17 +293,19 @@ async def accept_message_delivery(
                 existing = connection.execute(
                     "SELECT * FROM message_deliveries WHERE delivery_id=?",
                     (delivery_id,),
                 ).fetchone()
                 retrying = True
             if not retrying:
                 connection.commit()
                 return _resource(existing, acceptance="ALREADY_ACCEPTED"), 202
-            resource = _resource(existing, acceptance="ALREADY_ACCEPTED")
+            resource = _resource(
+                existing, acceptance="ALREADY_ACCEPTED", connection=connection,
+            )
         if not retrying:
             connection.execute(
                 """INSERT INTO message_deliveries (
                     delivery_id, schema_version, source_session_id, source_principal,
                     source_name, source_scope, source_task_id, target_session_id,
                     target_name, target_scope, target_task_id, target_generation,
                     message, rendered_message, message_kind, wake, payload_hash,
                     origin, origin_detail,
@@ -306,17 +321,17 @@ async def accept_message_delivery(
                     json.dumps(wait_error(quota_wait), ensure_ascii=False)
                     if quota_wait is not None else None,
                     now, now,
                 ),
             )
             inserted_row = connection.execute(
                 "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
             ).fetchone()
-            resource = _resource(inserted_row)
+            resource = _resource(inserted_row, connection=connection)
             inserted = True
         connection.commit()
         wake_runner = (inserted or retrying) and quota_wait is None
     except Exception:
         try:
             connection.rollback()
         except Exception:
             pass
@@ -370,22 +385,22 @@ def prepare_message_delivery(delivery_id: str) -> dict:
                    SET state='PREPARING', user_log_id=?, updated_at=?
                    WHERE delivery_id=? AND state='QUEUED'""",
                 (cursor.lastrowid, _now(), delivery_id),
             )
             row = connection.execute(
                 "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
             ).fetchone()
         if row["state"] != "PREPARING":
-            return _resource(row)
+            return _resource(row, connection=connection)
         user_log = connection.execute(
             "SELECT content FROM logs WHERE id=?", (row["user_log_id"],)
         ).fetchone()
         return {
-            **_resource(row),
+            **_resource(row, connection=connection),
             "user_log_id": row["user_log_id"],
             "history_user_message": user_log["content"] if user_log else row["rendered_message"],
             "provenance": MessageProvenance.from_storage(
                 row["origin"], row["origin_detail"]
             ),
         }
 
 
@@ -411,17 +426,17 @@ def _update_state(delivery_id: str, state: str, *, provider_ref: str | None = No
             )
             connection.execute(
                 "UPDATE message_deliveries SET user_log_id=NULL WHERE delivery_id=?",
                 (delivery_id,),
             )
         row = connection.execute(
             "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
         ).fetchone()
-        return _resource(row)
+        return _resource(row, connection=connection)
 
 
 def mark_message_delivery_dispatching(delivery_id: str) -> dict:
     row = _row(_validate_id(delivery_id))
     if row is None or row["state"] != "PREPARING":
         raise RuntimeError(f"message delivery {delivery_id} cannot dispatch")
     return _update_state(delivery_id, "DISPATCHING")
 
@@ -750,25 +765,30 @@ def complete_recovered_mailbox_delivery(
 def targets_with_uncertain_delivery() -> set[str]:
     """One batch projection for the session list, not one DB query per worker."""
     with db._conn() as connection:
         return {row[0] for row in connection.execute(
             "SELECT DISTINCT target_session_id FROM message_deliveries WHERE state='DELIVERY_UNKNOWN'"
         )}
 
 
-def _next_target_delivery(target_session_id: str) -> sqlite3.Row | None:
+def _next_target_delivery(
+    target_session_id: str,
+    *,
+    connection: sqlite3.Connection | None = None,
+) -> sqlite3.Row | None:
     placeholders = ",".join("?" * len(_TERMINAL_DELIVERY_STATES))
-    with db._conn() as connection:
-        return connection.execute(
-            f"""SELECT * FROM message_deliveries
-               WHERE target_session_id=? AND state NOT IN ({placeholders})
-               ORDER BY accept_seq LIMIT 1""",
-            (target_session_id, *_TERMINAL_DELIVERY_STATES),
-        ).fetchone()
+    sql = f"""SELECT * FROM message_deliveries
+             WHERE target_session_id=? AND state NOT IN ({placeholders})
+             ORDER BY accept_seq LIMIT 1"""
+    params = (target_session_id, *_TERMINAL_DELIVERY_STATES)
+    if connection is not None:
+        return connection.execute(sql, params).fetchone()
+    with db._conn() as current:
+        return current.execute(sql, params).fetchone()
 
 
 async def run_message_delivery(delivery_id: str, manager=None) -> None:
     row = _row(_validate_id(delivery_id))
     if row is None:
         raise KeyError(f"message delivery not found: {delivery_id}")
     from app import fan_barrier
 
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index f502aede9..b147cec04 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -706,23 +706,22 @@ async def stream_session_logs(name: str, scope: str, request: Request, after_id:
         finally:
             broker.unsubscribe(session_id, q)
             c.close()
     return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
 
 
 @router.get("/api/sessions/{name}/logs")
-async def get_session_logs(name: str, response: Response, scope: str,
+async def get_session_logs(name: str, request: Request, scope: str,
                            after_id: int = 0, before_id: int = 0,
                            limit: int = 500, max_bytes: int = 0, cap: int = 0):
     # Live chat snapshots are authoritative state, not an asset. A browser/intermediary
     # replaying an older 200 here recreates the exact "old messages, then SSE catches up"
     # staircase that the network-first client is designed to eliminate.
-    response.headers["Cache-Control"] = "no-store"
     limit = min(limit, 1000)
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
 
     def annotate(log: dict) -> dict:
         result = annotate_user_message(log)
         if result.get("type") != "status":
@@ -735,17 +734,23 @@ async def get_session_logs(name: str, response: Response, scope: str,
         }
 
     if before_id > 0:
         logs = get_logs_before(session_id, before_id, limit,
                                max(0, min(max_bytes, 1 << 20)),
                                max(0, min(cap, 1 << 20)))
     else:
         logs = get_logs(session_id, after_id=after_id)
-    return [annotate(log) for log in logs]
+    payload = [annotate(log) for log in logs]
+    body = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
+    tag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
+    headers = {"ETag": tag, "Cache-Control": "no-store"}
+    if request.headers.get("if-none-match") == tag:
+        return Response(status_code=304, headers=headers)
+    return JSONResponse(payload, headers=headers)
 
 
 @router.get("/api/logs/sync")
 async def logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384):
     """Зеркало журнала для браузера: все сессии всех проектов одним ответом.
 
     Scope не принимает намеренно — пользователь один, а логи ключуются по session_id.
     ``tail=0`` — карта сессий без строк журнала; дашборд ходит именно так с #72, потому
@@ -1046,16 +1051,38 @@ async def send_message(name: str, req: SendRequest, request: Request = None):
                     message=req.message,
                     rendered_message=rendered,
                     message_kind=req.message_kind,
                     wake=req.wake,
                     provenance=provenance,
                     quota_wait=quota_wait,
                 )
             return JSONResponse(resource, status_code=status_code)
+        if request is not None:
+            from app.mcp_proof import check_mcp_proof
+
+            source_id = request.headers.get("x-orchestra-session-id", "").strip()
+            source = get_session_row(source_id) if source_id else None
+            authenticated_sender = bool(
+                source and check_mcp_proof(
+                    source_id, request.headers.get("x-orchestra-mcp-proof", "")
+                )
+            )
+            if authenticated_sender: