# Candidate cand-44

## ORIGIN commit 38caf30b21 (2026-07-17): WIP: auto-saved uncommitted changes before worker spawn (2026-07-17 12:03)
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index 705e3fa89..57e4e17c5 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -25,16 +25,18 @@ from claude_agent_sdk import (
 from claude_agent_sdk.types import (
     ToolResultBlock, ServerToolResultBlock, UserMessage,
 )
 
 from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
 
+CLAUDE_INTERRUPT_TIMEOUT = 5.0
+
 _BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
 _ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
 # Orchestrators must use spawn_worker instead of the built-in Agent/Task tools —
 # those bypass Orchestra's worktree isolation and session tracking.
 # Blocked via disallowed_tools (not can_use_tool) because subagent launches arrive
 # as TaskStartedMessage, which the permission callback never sees.
 _ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]
 # ScheduleWakeup/Cron* removed for all agents — Orchestra manages scheduling via bg_jobs
@@ -106,16 +108,17 @@ class ClaudeBackend:
         self._config_dir = config_dir
         # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
         self._inherit_claude_md = inherit_claude_md
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
         self._effort = effort
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
+        self._pending_model_error = ""
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     def _make_client(self) -> ClaudeSDKClient:
         import os
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
@@ -194,22 +197,40 @@ class ClaudeBackend:
 
     async def events(self) -> AsyncIterator[AgentEvent]:
         if not self._client:
             return
         async for msg in self._client.receive_messages():
             for event in self._convert(msg):
                 yield event
 
-    async def interrupt(self) -> None:
-        if self._client:
-            try:
-                await self._client.interrupt()
-            except Exception as e:
-                logger.warning(f"ClaudeBackend interrupt failed: {e}")
+    async def interrupt(self) -> bool:
+        """Interrupt the active turn, returning whether the CLI acknowledged it.
+
+        The SDK's control request waits up to 60 seconds by default. Orchestra needs a
+        short bound so a broken control channel cannot leave the Stop request hanging;
+        the session layer hard-disconnects this backend when False is returned.
+        """
+        if not self._client:
+            return True
+        try:
+            await asyncio.wait_for(
+                self._client.interrupt(),
+                timeout=CLAUDE_INTERRUPT_TIMEOUT,
+            )
+            return True
+        except asyncio.TimeoutError:
+            logger.error(
+                "ClaudeBackend interrupt was not acknowledged within %.1fs",
+                CLAUDE_INTERRUPT_TIMEOUT,
+            )
+            return False
+        except Exception as e:
+            logger.warning(f"ClaudeBackend interrupt failed: {e}")
+            return False
 
     async def disconnect(self) -> None:
         if self._client:
             try:
                 await self._client.disconnect()
             except Exception as e:
                 logger.warning(f"ClaudeBackend disconnect failed: {e}")
             self._client = None
@@ -305,17 +326,22 @@ class ClaudeBackend:
                         inp = str(block.input)
                     short_name = block.name.split('__')[-1] if '__' in block.name else block.name
                     events.append(self._tag_sub(AgentEvent("tool_use", f"{block.name}: {inp}",
                                              metadata={"tool_name": block.name, "short_name": short_name}), sub_id))
                 elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                     events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
             err = getattr(msg, "error", None)
             if err:
-                events.append(AgentEvent("error", f"model error: {err}"))
+                self._pending_model_error = str(err)
+                events.append(AgentEvent(
+                    "error",
+                    f"model error: {err}",
+                    metadata={"model_error": str(err)},
+                ))
 
         elif isinstance(msg, UserMessage):
             sub_id = getattr(msg, "parent_tool_use_id", None)
             if hasattr(msg, 'content') and isinstance(msg.content, list):
                 for block in msg.content:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                         events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
@@ -358,18 +384,22 @@ class ClaudeBackend:
                                                **u}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
 
-            is_err = bool(getattr(msg, "is_error", False))
-            err_list = getattr(msg, "errors", None) or []
+            model_error = self._pending_model_error
+            self._pending_model_error = ""
+            is_err = bool(getattr(msg, "is_error", False) or model_error)
+            err_list = list(getattr(msg, "errors", None) or [])
+            if model_error and model_error not in err_list:
+                err_list.append(model_error)
             denials = getattr(msg, "permission_denials", None) or []
 
             cost = getattr(msg, "total_cost_usd", 0) or 0
             usage = getattr(msg, "usage", None)
             max_tokens = 200000
             cache_hit = 0
             cache_read = 0
             cache_create = 0
@@ -402,16 +432,17 @@ class ClaudeBackend:
             if denials:
                 logger.info(f"[{self.model}] {len(denials)} permission denial(s) this turn")
 
             events.append(AgentEvent("turn_end", f"stop_reason={sr}, num_turns={nt}", metadata={
                 "session_id": self._session_id,
                 "ok": not is_err,
                 "is_error": is_err,
                 "errors": err_list,
+                "model_error": model_error,
                 "stop_reason": sr,
                 "num_turns": nt,
                 "cost_usd": cost,
                 "cost_usd_cached": round(cost_cached, 6),
                 "context_pct": 0,
                 "context_tokens": 0,
                 "max_tokens": max_tokens,
                 "cache_hit": cache_hit,
diff --git a/app/backend_codex.py b/app/backend_codex.py
index f5ae78219..35eedb379 100644
--- a/app/backend_codex.py
+++ b/app/backend_codex.py
@@ -146,16 +146,21 @@ class CodexBackend:
         self._got_turn_completed: bool = False
         self._rollout_path: Path | None = None
         self._usage_baseline: dict[str, int] | None = None
 
     @property
     def session_id(self) -> Optional[str]:
         return self._thread_id
 
+    @property
+    def is_alive(self) -> bool:
+        """Whether the per-turn Codex subprocess is still running."""
+        return self._proc is not None and self._proc.returncode is None
+
     async def connect(self) -> None:
         # Codex launches a new subprocess per turn (stateless CLI), so connect is a no-op —
         # the actual process starts in send() when the first message arrives
         pass
 
     async def send(self, message: str) -> None:
         self._got_turn_completed = False
         self._last_stderr = ""
@@ -224,17 +229,23 @@ class CodexBackend:
             except json.JSONDecodeError:
                 continue
 
             etype = data.get("type", "")
 
             if etype == "thread.started":
                 self._thread_id = data["thread_id"]
                 self._rollout_path = None
-                yield AgentEvent("status", f"codex thread={self._thread_id}")
+                # Persist the resumable thread immediately. A transport failure or
+                # service shutdown can happen before turn.completed arrives.
+                yield AgentEvent(
+                    "status",
+                    f"codex thread={self._thread_id}",
+                    metadata={"session_id": self._thread_id},
+                )
 
             elif etype == "item.completed":
                 item = data.get("item", {})
                 itype = item.get("type", "")
 
                 if itype == "agent_message":
                     yield AgentEvent("text", item.get("text", ""))
 
diff --git a/app/backend_protocol.py b/app/backend_protocol.py
index a2296f6fb..a706a6da5 100644
--- a/app/backend_protocol.py
+++ b/app/backend_protocol.py
@@ -6,10 +6,10 @@ from app.events import AgentEvent
 
 
 class BackendLike(Protocol):
     @property
     def session_id(self) -> Optional[str]: ...
     async def connect(self) -> None: ...
     async def send(self, message: str) -> None: ...
     async def events(self) -> AsyncIterator[AgentEvent]: ...
-    async def interrupt(self) -> None: ...
+    async def interrupt(self) -> bool | None: ...
     async def disconnect(self) -> None: ...
diff --git a/app/db.py b/app/db.py
index 4ed5d7aa2..1571c834f 100644
--- a/app/db.py
+++ b/app/db.py
@@ -741,16 +741,25 @@ def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
     for k in _SA_TEXT:
         if k in fields and fields[k] is not None:
             cols.append(k); vals.append(fields[k])
             updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
     for k in _SA_NUM:
         if k in fields and fields[k]:
             cols.append(k); vals.append(int(fields[k]))
             updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
+    if fields.get("ended_at") and not fields.get("duration_ms"):
+        # local_bash notifications carry no TaskUsage. Preserve SDK duration
+        # when present; otherwise derive wall time from the persisted lifecycle.
+        updates.append(
+            "duration_ms=CASE WHEN subagents.duration_ms > 0 "
+            "THEN subagents.duration_ms ELSE MAX(0, CAST("
+            "(julianday(excluded.ended_at) - julianday(subagents.started_at)) "
+            "* 86400000 AS INTEGER)) END"
+        )
     placeholders = ", ".join("?" for _ in cols)
     set_clause = ", ".join(updates) if updates else "task_id=task_id"
     with _conn() as c:
         c.execute(
             f"INSERT INTO subagents ({', '.join(cols)}) VALUES ({placeholders}) "
             f"ON CONFLICT(session_id, task_id) DO UPDATE SET {set_clause}",
             vals,
         )
diff --git a/app/manager.py b/app/manager.py
index 9cf7be76b..cdbab05d1 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1064,29 +1064,42 @@ class SessionManager:
         if not session:
             return ""
         pct = session._last_context.get("percentage", 0)
         if pct >= 90:
             return f"\n⚠️ CONTEXT CRITICAL: {pct}% — do NOT send more tasks to this worker"
         return ""
 
     def _make_idle_callback(self, scope: str):
-        async def _on_worker_idle(worker_name: str, worker_scope: str, last_texts: list[str], stop_reason: str = ""):
+        async def _on_worker_idle(
+                worker_name: str,
+                worker_scope: str,
+                last_texts: list[str],
+                stop_reason: str = "",
+                turn_ok: bool = True):
             worker_session = next((s for s in self.sessions.values() if s.name == worker_name), None)
             parent = worker_session.parent_name if worker_session else None
             orch = parent or self._find_orchestrator_name(scope)
             if not orch:
                 return
             orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
             if not orch_session:
                 return
             summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
             ctx = self._context_warning(worker_name)
             sr = f" (stop_reason={stop_reason})" if stop_reason else ""
-            msg = f"[from:{worker_name}] [auto-report]{sr} Finished without explicit report. Last output:\n{summary}{ctx}"
+            outcome = (
+                "Finished without explicit report"
+                if turn_ok
+                else "Turn failed before an explicit report"
+            )
+            msg = (
+                f"[from:{worker_name}] [auto-report]{sr} {outcome}. "
+                f"Last output:\n{summary}{ctx}"
+            )
             logger.info(f"Auto-report: {worker_name} → {orch}")
             await orch_session.send(msg)
         return _on_worker_idle
 
     # ── Listings ──
 
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
diff --git a/app/routes/subagent.py b/app/routes/subagent.py
index f4f68030c..4695736d8 100644
--- a/app/routes/subagent.py
+++ b/app/routes/subagent.py
@@ -1,65 +1,129 @@
 """Sub-agent telemetry + transcript routes.
 
 Telemetry (tokens/summary/output_file/status) comes from the DB `subagents`
 table (populated from Task* SDK messages). Full transcripts are read lazily
 from the SDK's JSONL store via list_subagents / get_subagent_messages — NOT
-duplicated in our DB. agent_id (SDK file id) != task_id (Task message id), so
-transcript listing is independent of the telemetry table.
+duplicated in our DB. For local_agent tasks the SDK task_id is the transcript
+agent_id; local_bash tasks are background processes and have no transcript.
 """
 
 import logging
 import re
+from datetime import datetime
 
 from fastapi import APIRouter
 from fastapi.responses import JSONResponse
 
-from app.db import get_subagents, get_session
+from app.db import get_subagent, get_subagents, get_session
 
 logger = logging.getLogger("orchestra.subagent")
 
 router = APIRouter(tags=["subagent"])
 
 _SAFE_ID = re.compile(r"^[\w-]+$")  # agent_id goes into a filename — no path traversal
 
 
+def _duration_ms(row: dict) -> int:
+    """Return SDK duration or derive wall time for legacy/background rows."""
+    duration = int(row.get("duration_ms") or 0)
+    if duration or not row.get("started_at") or not row.get("ended_at"):
+        return duration
+    try:
+        started = datetime.fromisoformat(row["started_at"])
+        ended = datetime.fromisoformat(row["ended_at"])
+    except (TypeError, ValueError):
+        return 0
+    return max(0, round((ended - started).total_seconds() * 1000))
+
+
+def _transcript_ids(rows: list[dict], cwd: str) -> set[str]:
+    """Find persisted local-agent transcripts across all SDK session rotations."""
+    from claude_agent_sdk import list_subagents
+
+    wanted_by_sdk: dict[str, set[str]] = {}
+    for row in rows:
+        if row.get("task_type") == "local_bash":
+            continue
+        sdk_id = row.get("sdk_session_id") or ""
+        task_id = row.get("task_id") or ""
+        if sdk_id and task_id:
+            wanted_by_sdk.setdefault(sdk_id, set()).add(task_id)
+
+    available: set[str] = set()
+    for sdk_id, wanted in wanted_by_sdk.items():
+        try:
+            available.update(wanted.intersection(list_subagents(sdk_id, cwd or None)))
+        except Exception as e:
+            logger.warning("list_subagents failed for %s: %s", sdk_id, e)
+    return available
+
+
 @router.get("/api/subagents/{session_id}")
 async def subagents_list(session_id: str):
-    """Telemetry rows for a session's sub-agents (from Task* messages)."""
-    return {"subagents": get_subagents(session_id)}
+    """Telemetry for real SDK agents and background tasks, explicitly typed."""
+    rows = get_subagents(session_id)
+    sess = get_session(session_id)
+    available = _transcript_ids(rows, (sess or {}).get("cwd") or "") if sess else set()
+    out = []
+    for source in rows:
+        row = dict(source)
+        is_background = row.get("task_type") == "local_bash"
+        row["kind"] = "background" if is_background else "agent"
+        row["duration_ms"] = _duration_ms(row)
+        row["transcript_id"] = (
+            row.get("task_id") or ""
+        ) if not is_background and row.get("task_id") in available else ""
+        out.append(row)
+    return {"subagents": out}
 
 
 @router.get("/api/subagent-transcripts/{session_id}")
 async def subagent_transcript_ids(session_id: str):
-    """SDK agent_ids of sub-agents whose transcripts exist for this session."""
+    """SDK agent_ids represented by telemetry, including older SDK sessions."""
     sess = get_session(session_id)
     if not sess:
         return JSONResponse({"error": "session not found"}, status_code=404)
-    sdk_id = sess.get("session_id") or ""
-    if not sdk_id:
+    rows = get_subagents(session_id)
+    if not rows and not (sess.get("session_id") or ""):
         return {"agent_ids": [], "note": "no sdk_session_id yet"}
-    from claude_agent_sdk import list_subagents
-    try:
-        agent_ids = list_subagents(sdk_id, sess.get("cwd") or None)
-    except Exception as e:
-        logger.warning(f"list_subagents failed: {e}")
-        return {"agent_ids": [], "error": str(e)}
-    return {"agent_ids": agent_ids, "sdk_session_id": sdk_id}
+    agent_ids = _transcript_ids(rows, sess.get("cwd") or "")
+    current_sdk_id = sess.get("session_id") or ""
+    if current_sdk_id:
+        from claude_agent_sdk import list_subagents
+        try:
+            agent_ids.update(list_subagents(
+                current_sdk_id,
+                sess.get("cwd") or None,
+            ))
+        except Exception as e:
+            logger.warning("list_subagents failed for %s: %s", current_sdk_id, e)
+    return {"agent_ids": sorted(agent_ids), "sdk_session_id": current_sdk_id}
 
 
 @router.get("/api/subagent-transcript/{session_id}/{agent_id}")
 async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
     """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
     if not _SAFE_ID.match(agent_id):
         return JSONResponse({"error": "invalid agent_id"}, status_code=400)
     sess = get_session(session_id)
     if not sess:
         return JSONResponse({"error": "session not found"}, status_code=404)
-    sdk_id = sess.get("session_id") or ""
+    telemetry = get_subagent(session_id, agent_id)
+    if telemetry and telemetry.get("task_type") == "local_bash":
+        return {
+            "messages": [],
+            "note": "background tasks do not have transcripts",
+        }
+    sdk_id = (
+        (telemetry or {}).get("sdk_session_id")
+        or sess.get("session_id")
+        or ""
+    )
     if not sdk_id:
         return {"messages": [], "note": "no sdk_session_id yet"}
     from claude_agent_sdk import get_subagent_messages
     try:
         msgs = get_subagent_messages(sdk_id, agent_id, sess.get("cwd") or None,
                                      limit=limit, offset=offset)
     except Exception as e:
         logger.warning(f"get_subagent_messages failed: {e}")
diff --git a/app/session.py b/app/session.py
index 43a36fb07..4fd7aecd9 100644
--- a/app/session.py
+++ b/app/session.py
@@ -188,22 +188,25 @@ class AgentSession:
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _persist_dirty: bool = field(default=False, repr=False)
     _turn_gen: int = field(default=0, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
     _auto_continue_count: int = field(default=0, repr=False)
     _rate_limit_retries: int = field(default=0, repr=False)
+    _server_error_retries: int = field(default=0, repr=False)
     _session_limit_hit: bool = field(default=False, repr=False)
     _manually_interrupted: bool = field(default=False, repr=False)
 
     AUTO_CONTINUE_MAX = 5
     RATE_LIMIT_MAX_RETRIES = 3
     RATE_LIMIT_DELAY = 30
+    SERVER_ERROR_MAX_RETRIES = 3
+    SERVER_ERROR_RETRY_DELAY = 5
 
     def __post_init__(self) -> None:
         # Systems over state (ECS): cost/turn/hibernate methods live in systems,
         # all fields stay on the session (persistence reads them directly)
         self._cost = CostTracker(self)
         self._turns = TurnManager(self)
         self._hibernate = HibernateManager(self)
 
@@ -312,20 +315,22 @@ class AgentSession:
     async def start(self, initial_message: str | None = None) -> None:
         if initial_message:
             await self.send(initial_message)
         else:
             self.status = AgentStatus.IDLE
             self._persist()
 
     async def send(self, message: str) -> None:
+        # Retry budgets belong to one logical request. A real new message resets both;
+        # each internal retry preserves only its own failure class.
         if not message.startswith("[system] Retrying after rate limit."):
-            # Retry budget belongs to one logical request. A real new message starts a new
-            # budget; internal retry turns deliberately preserve the current count.
             self._rate_limit_retries = 0
+        if not message.startswith("[system] Retrying after transient server error."):
+            self._server_error_retries = 0
             self._session_limit_hit = False
         if self._compacting:
             self._pending_messages.append(message)
             self._log("user_message", message)
             self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
             return
 
         if self.status == AgentStatus.RUNNING:
@@ -896,16 +901,37 @@ class AgentSession:
         try:
             await self.send("[system] Retrying after rate limit. Continue where you left off.")
             logger.info(f"[{self.name}] rate-limit retry after {delay}s")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
             self.status = AgentStatus.IDLE
             self._persist()
 
+    async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
+        """Resume through a fresh SDK transport after an upstream stream failure."""
+        await asyncio.sleep(delay)
+        try:
+            async with self._lifecycle_lock:
+                # A real user message already started a newer turn; it supersedes this
+                # automatic retry and must not be duplicated.
+                if self._turn_gen != expected_turn_gen or self.status != AgentStatus.IDLE:
+                    return
+                await self._disconnect_backend()
+            await self.send(
+                "[system] Retrying after transient server error. Continue where you "
+                "left off. Do not repeat completed research; execute the pending "
+                "deliverable now."
+            )
+            logger.info(f"[{self.name}] server-error retry after {delay}s")
+        except Exception as e:
+            logger.warning(f"[{self.name}] server-error retry failed: {e}")
+            self.status = AgentStatus.IDLE
+            self._persist()
+
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             await self.send("[system] Turn limit reached. Continue where you left off.")
             logger.info(f"[{self.name}] auto-continue after max_turns")
         except Exception as e:
             logger.warning(f"[{self.name}] auto-continue failed: {e}")
             self.status = AgentStatus.IDLE
diff --git a/app/session_hibernate.py b/app/session_hibernate.py
index bb77db8ad..4565c3f5c 100644
--- a/app/session_hibernate.py
+++ b/app/session_hibernate.py
@@ -12,24 +12,38 @@ from app.session_state import (
     AgentStatus, IDLE_TIMEOUT_ORCHESTRATOR, IDLE_TIMEOUT_WORKER,
 )
 
 if TYPE_CHECKING:
     from app.session import AgentSession
 
 logger = logging.getLogger("app.session")
 
-ZOMBIE_TIMEOUT_CODEX = 600
+CODEX_SILENCE_WARNING = 600
 ZOMBIE_TIMEOUT_CLAUDE = 1800
 HEARTBEAT_INTERVAL = 60
 
 
 class HibernateManager:
     def __init__(self, s: "AgentSession") -> None:
         self.s = s
+        self._last_codex_silence_warning = 0.0
+
+    @staticmethod
+    def _codex_runtime_dead(s: "AgentSession") -> bool:
+        """Return true only when a Codex runtime component is definitely gone.
+
+        Silence alone is not proof: Codex may spend a long time reasoning or running a
+        tool without producing JSONL events. Process and listener state are observable.
+        """
+        if s._backend is None:
+            return True
+        if s._listen_task is None or s._listen_task.done():
+            return True
+        return getattr(s._backend, "is_alive", None) is False
 
     def schedule(self) -> None:
         s = self.s
         if s._hibernate_task and not s._hibernate_task.done():
             s._hibernate_task.cancel()
         if s.backend_type != "claude":
             return
         timeout = IDLE_TIMEOUT_ORCHESTRATOR if s.is_orchestrator else IDLE_TIMEOUT_WORKER
@@ -55,28 +69,46 @@ class HibernateManager:
     async def heartbeat_loop(self) -> None:
         s = self.s
         logger.info(f"[{s.name}] heartbeat started")
         while True:
             try:
                 await asyncio.sleep(HEARTBEAT_INTERVAL)
 
                 if s.status == AgentStatus.RUNNING and s._last_msg_time > 0:
-                    silence = asyncio.get_event_loop().time() - s._last_msg_time
-                    zombie_timeout = ZOMBIE_TIMEOUT_CODEX if s.backend_type == "codex" else ZOMBIE_TIMEOUT_CLAUDE
+                    now = asyncio.get_event_loop().time()
+                    silence = now - s._last_msg_time
+                    zombie_timeout = CODEX_SILENCE_WARNING if s.backend_type == "codex" else ZOMBIE_TIMEOUT_CLAUDE
                     if silence > zombie_timeout:
-                        if s.backend_type == "codex" or s._backend is None:
-                            logger.error(f"[{s.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend={'alive' if s._backend else 'dead'})")
+                        if s.backend_type == "codex" and self._codex_runtime_dead(s):
+                            logger.error(f"[{s.name}] heartbeat: dead Codex runtime detected ({silence:.0f}s silence)")
                             s._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
                             if s._backend:
                                 await s._disconnect_backend()
                             s.status = AgentStatus.IDLE
                             s._persist()
                             if s._pending_messages:
                                 s._spawn_bg(s._flush_pending())
+                        elif s.backend_type == "codex":
+                            # Long quiet turns are valid. Keep them alive and report at
+                            # most once per warning interval; manual interrupt remains
+                            # available for a genuinely wedged upstream process.
+                            if now - self._last_codex_silence_warning >= CODEX_SILENCE_WARNING:
+                                logger.warning(
+                                    f"[{s.name}] heartbeat: {silence:.0f}s silence, "
+                                    "Codex process and listener still alive"
+                                )
+                                self._last_codex_silence_warning = now
+                        elif s._backend is None:
+                            logger.error(f"[{s.name}] heartbeat: zombie detected ({silence:.0f}s silence, backend=dead)")
+                            s._log("error", f"zombie detected: {silence:.0f}s silence, auto-recovering")
+                            s.status = AgentStatus.IDLE
+                            s._persist()
+                            if s._pending_messages:
+                                s._spawn_bg(s._flush_pending())
                         else:
                             logger.warning(f"[{s.name}] heartbeat: {silence:.0f}s silence during RUNNING turn")
                             s._log("status", f"no messages for {silence:.0f}s during active turn (possible long thinking)")
 
                 if s._backend is None:
                     continue
 
                 task_dead = s._listen_task is None or s._listen_task.done()
diff --git a/app/session_turns.py b/app/session_turns.py
index 4b84717b4..634a67f89 100644
--- a/app/session_turns.py
+++ b/app/session_turns.py
@@ -96,17 +96,23 @@ class TurnManager:
         # no need to spam the orchestrator with auto-report
         if not s.last_task_sender:
             return
         last_texts = s._turn_logs[-5:] if s._turn_logs else []
         stop_reason = s._last_stop_reason
 
         async def _do_report():
             try:
-                await s.on_idle(s.name, s.scope, last_texts, stop_reason)
+                await s.on_idle(
+                    s.name,
+                    s.scope,
+                    last_texts,
+                    stop_reason,
+                    s._last_turn_ok,
+                )
             except Exception as e:
                 logger.error(f"Auto-report failed for {s.name}: {e}")
 
         s._auto_report_task = asyncio.create_task(_do_report())
 
     def handle_turn_end(self, event: AgentEvent) -> None:
         s = self.s
         meta = event.metadata
@@ -133,56 +139,80 @@ class TurnManager:
                 s._auto_continue_count += 1
                 s._log("status", f"{sr} ({nt} turns), auto-continuing "
                                  f"({s._auto_continue_count}/{s.AUTO_CONTINUE_MAX})")
                 s._spawn_bg(s._auto_continue())
                 return
         else:
             s._auto_continue_count = 0
 
+        server_error_retry = None
+        model_error = str(meta.get("model_error") or "")
+        if not ok and model_error == "server_error":
+            if s._server_error_retries < s.SERVER_ERROR_MAX_RETRIES:
+                s._server_error_retries += 1
+                delay = s.SERVER_ERROR_RETRY_DELAY * s._server_error_retries
+                server_error_retry = (delay, s._turn_gen)
+                s._log(
+                    "status",
+                    f"transient server_error — fresh-backend retry in {delay}s "
+                    f"({s._server_error_retries}/{s.SERVER_ERROR_MAX_RETRIES})",
+                )
+            else:
+                s._log(
+                    "error",
+                    f"server_error — gave up after {s.SERVER_ERROR_MAX_RETRIES} retries",
+                )
+
         live_pct = s._last_context.get("percentage", 0)
         ctx_s = f"ctx:{live_pct}%" if live_pct else ""
         def _fc(v):
             return f"{v:.4f}" if v < 0.01 and v > 0 else f"{v:.2f}"
         limits_s = _format_limits()
         s._log("status", f"turn ended ({sr}, {nt} turns, ${_fc(s._turn_cost)} turn, ${_fc(s._context_cost)} ctx, ${_fc(s._session_cost)} session, ${_fc(s.cost_usd)} total {ctx_s}){limits_s}")
 
         self.finish_turn_status()
-        self.after_turn_idle_actions(live_pct)
+        self.after_turn_idle_actions(
+            live_pct,
+            allow_auto_report=server_error_retry is None,
+        )
+        if server_error_retry is not None:
+            s._spawn_bg(s._retry_after_server_error(*server_error_retry))
 
     def finish_turn_status(self) -> None:
         """Set IDLE or WAITING based on bg jobs, then persist."""
         s = self.s
         from app.bg_jobs import bg_manager
         if bg_manager and bg_manager.has_active_jobs(s.id):
             s.status = AgentStatus.WAITING
             s._log("status", "waiting for bg jobs")
         else:
             s.status = AgentStatus.IDLE
             s.progress_pct = 0
             s.progress_status = ""
         s._persist()
 
-    def after_turn_idle_actions(self, live_pct: int) -> None:
+    def after_turn_idle_actions(
+            self, live_pct: int, *, allow_auto_report: bool = True) -> None:
         """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
         s = self.s
         if s._compact_ack_event is not None and s._turn_gen == s._compact_ack_gen:
             s._compact_ack_event.set()
 
         s._spawn_bg(s._notify_scope_idle())
 
         if live_pct > 90 and not s.is_orchestrator and not s._compacting:
             # Workers auto-compact to stay operational; orchestrators are left for
             # the user to compact manually since they hold long-running session state
             s._log("status", f"auto-compact triggered ({live_pct}%)")
             s._spawn_bg(s._auto_compact())
 
         # Don't auto-report mid-flight: WAITING means a bg job (e.g. codex_review) is
         # still running and will wake the worker with its result — the turn isn't
         # really "done", so reporting now spams a half-status to the orchestrator.
-        if s.status != AgentStatus.WAITING:
+        if allow_auto_report and s.status != AgentStatus.WAITING:
             self.fire_auto_report()
 
         if s._pending_messages:
             s._spawn_bg(s._flush_pending())
             return
 
         s._hibernate.schedule()
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 7b0b7e904..c434269ad 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -4831,29 +4831,43 @@ function closeSubagentsModal() {
 function _subagentsEscHandler(e) { if (e.key === 'Escape') closeSubagentsModal(); }
 
 async function _loadSubagents() {
     const body = document.getElementById('subagents-body');
     if (!body) return;
     body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
     try {
         const sid = manager_session_id_for(selectedAgent);
-        // Telemetry + transcript agent_ids in parallel. agent_id (SDK file id) != task_id,
-        // so map telemetry cards → transcript ids by index (both time-ordered).
-        const [data, tData] = await Promise.all([
-            api(`/api/subagents/${encodeURIComponent(sid)}`),
-            api(`/api/subagent-transcripts/${encodeURIComponent(sid)}`).catch(() => ({ agent_ids: [] })),
-        ]);
+        const data = await api(`/api/subagents/${encodeURIComponent(sid)}`);
         const subs = (data && data.subagents) || [];
-        const agentIds = (tData && tData.agent_ids) || [];
         if (!subs.length) {
-            body.innerHTML = '<div class="text-center text-slate-500 py-8 italic">Этот агент ещё не запускал субагентов.</div>';
+            body.innerHTML = '<div class="text-center text-slate-500 py-8 italic">Здесь пока нет ни SDK-агентов, ни фоновых задач.</div>';
             return;
         }
-        body.innerHTML = subs.map((s, i) => _renderSubagentCard(s, i, agentIds[i] || '')).join('');
+        const byNewest = (a, b) => String(b.started_at || '').localeCompare(String(a.started_at || ''));
+        const agents = subs.filter(s => s.kind !== 'background').sort(byNewest);
+        const jobs = subs.filter(s => s.kind === 'background').sort(byNewest);
+        const activeCount = subs.filter(s => s.status === 'running').length;
+
+        const sections = [
+            `<div class="mb-4 flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
+                <span class="rounded-full bg-purple-500/10 px-2 py-1 text-purple-300">🤖 SDK-агенты: ${agents.length}</span>
+                <span class="rounded-full bg-sky-500/10 px-2 py-1 text-sky-300">⚙️ Фоновые задачи: ${jobs.length}</span>
+                ${activeCount ? `<span class="rounded-full bg-amber-500/10 px-2 py-1 text-amber-300">⏳ Активны: ${activeCount}</span>` : ''}
+            </div>`,
+        ];
+        if (agents.length) {
+            sections.push(`<section class="mb-5">
+                <h3 class="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-purple-300">SDK-агенты</h3>
+                ${agents.map((s, i) => _renderSubagentCard(s, i)).join('')}
+            </section>`);
+        }
+        if (jobs.length) sections.push(_renderBackgroundJobs(jobs));
+        body.innerHTML = sections.join('');
+
         // Wire transcript toggles
         body.querySelectorAll('.sa-transcript-btn').forEach(btn => {
             btn.addEventListener('click', () => _toggleTranscript(btn, sid));
         });
         body.querySelectorAll('.sa-summary-toggle').forEach(btn => {
             btn.addEventListener('click', () => {
                 const full = btn.nextElementSibling;
                 if (full) full.classList.toggle('hidden');
@@ -4881,70 +4895,129 @@ function _subagentTitle(s) {
     if (!t) t = (s.last_tool_name || 'Sub-agent');
     // If it's a long command dump, take up to the first structural boundary
     const boundary = t.search(/[;\n]|<</);
     if (boundary > 0 && boundary < 80) t = t.slice(0, boundary);
     t = t.replace(/\s+/g, ' ').trim();
     return t.length > 80 ? t.slice(0, 80) + '…' : t;
 }
 
-function _renderSubagentCard(s, idx, transcriptId) {
+function _subagentStatus(s) {
     const statusMap = {
         completed: ['🟢', '#22c55e', 'completed'],
         failed: ['🔴', '#ef4444', 'failed'],
         running: ['⏳', '#eab308', 'running'],
+        stopped: ['⏹️', '#94a3b8', 'stopped'],
     };
-    const [icon, color, label] = statusMap[s.status] || ['⚪', '#64748b', s.status || '?'];
+    return statusMap[s.status] || ['⚪', '#64748b', s.status || '?'];
+}
+
+function _subagentDuration(s) {
+    if (s.duration_ms) return _fmtDuration(s.duration_ms);
+    if (s.status === 'running' && s.started_at) {
+        const elapsed = Date.now() - new Date(s.started_at).getTime();
+        if (Number.isFinite(elapsed) && elapsed >= 0) return _fmtDuration(elapsed);
+    }
+    return '';
+}
+
+function _meaningfulSummary(s) {
+    const summary = String(s.summary || '').trim();
+    if (!summary) return '';
+    const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
+    return normalize(summary) === normalize(s.description) ? '' : summary;
+}
+
+function _renderSubagentCard(s, idx) {
+    const [icon, color, label] = _subagentStatus(s);
     const desc = _escHtml(_subagentTitle(s));
-    const taskType = s.task_type ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase" style="background:rgba(167,139,250,0.15);color:#c4b5fd">${_escHtml(s.task_type)}</span>` : '';
-    // "—" for missing data (local_bash sub-agents have no usage), not misleading "0"
-    const metrics = [
-        `🔢 ${s.total_tokens ? _fmtTokens(s.total_tokens) : '—'}`,
-        `🔧 ${s.tool_uses ? s.tool_uses : '—'}`,
-        `⏱️ ${s.duration_ms ? _fmtDuration(s.duration_ms) : '—'}`,
-    ];
+    const metrics = [];
+    if (s.total_tokens) metrics.push(`🔢 ${_fmtTokens(s.total_tokens)}`);
+    if (s.tool_uses) metrics.push(`🔧 ${s.tool_uses}`);
+    const duration = _subagentDuration(s);
+    if (duration) metrics.push(`⏱️ ${duration}`);
     if (s.last_tool_name) metrics.push(`⚙️ ${_escHtml(s.last_tool_name)}`);
 
     let summaryBlock = '';
-    if (s.summary) {
+    const summary = _meaningfulSummary(s);
+    if (summary) {
         summaryBlock = `<div class="mt-2">
             <button class="sa-summary-toggle text-[10px] text-indigo-300 hover:text-indigo-200">▶ Показать summary</button>
-            <div class="hidden mt-1 p-2 bg-slate-900/60 rounded-lg text-[11px] text-slate-300 whitespace-pre-wrap break-words">${_escHtml(s.summary)}</div>
+            <div class="hidden mt-1 p-2 bg-slate-900/60 rounded-lg text-[11px] text-slate-300 whitespace-pre-wrap break-words">${_escHtml(summary)}</div>
         </div>`;
     }
     let fileBlock = '';
     if (s.output_file) {
         fileBlock = `<div class="mt-1 text-[10px] text-slate-500">📄 <span class="text-emerald-400 break-all">${_escHtml(s.output_file)}</span></div>`;
     }
-    const agentId = transcriptId || '';
+    const agentId = s.transcript_id || '';
     const transcriptBtn = agentId
         ? `<button class="sa-transcript-btn text-[10px] px-2 py-1 bg-purple-600/30 hover:bg-purple-600/50 rounded-lg text-purple-200 transition-colors" data-agent-id="${_escHtml(agentId)}" data-idx="${idx}">📜 Транскрипт</button>
            <div class="sa-transcript-panel hidden mt-2"></div>`
-        : `<span class="text-[10px] text-slate-600 italic">транскрипт недоступен</span>`;
+        : `<span class="text-[10px] text-slate-600 italic">транскрипт ещё не записан</span>`;
 
     return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 mb-3" style="border-left:3px solid ${color}">
         <div class="flex items-start justify-between gap-2 mb-2">
             <div class="flex-1 min-w-0">
                 <div class="flex items-center gap-2 flex-wrap">
                     <span class="text-sm">🤖</span>
                     <span class="text-xs font-semibold text-white break-words">${desc}</span>
-                    ${taskType}
+                    <span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase" style="background:rgba(167,139,250,0.15);color:#c4b5fd">agent</span>
                 </div>
             </div>
             <span class="text-[10px] font-mono shrink-0" style="color:${color}">${icon} ${label}</span>
         </div>
-        <div class="flex items-center gap-3 flex-wrap text-[11px] text-slate-400">
-            ${metrics.map(m => `<span>${m}</span>`).join('')}
-        </div>
+        ${metrics.length ? `<div class="flex items-center gap-3 flex-wrap text-[11px] text-slate-400">${metrics.map(m => `<span>${m}</span>`).join('')}</div>` : ''}
         ${fileBlock}
         ${summaryBlock}
         <div class="mt-2">${transcriptBtn}</div>
     </div>`;
 }
 
+function _renderBackgroundJob(s) {
+    const [icon, color, label] = _subagentStatus(s);
+    const duration = _subagentDuration(s);
+    const summary = _meaningfulSummary(s);
+    const details = summary
+        ? `<div class="mt-1 text-[10px] text-slate-400">${_saCollapsible(summary, 180)}</div>`
+        : '';
+    const output = s.output_file
+        ? `<div class="mt-1 text-[10px] text-emerald-400 break-all">📄 ${_escHtml(s.output_file)}</div>`
+        : '';
+    return `<div class="rounded-lg border border-slate-800/80 bg-slate-950/30 px-3 py-2" style="border-left:2px solid ${color}">
+        <div class="flex items-start justify-between gap-3">
+            <div class="min-w-0 flex-1">
+                <div class="text-[11px] font-medium text-slate-200 break-words">${_escHtml(_subagentTitle(s))}</div>
+                ${details}${output}
+            </div>
+            <div class="shrink-0 text-right">
+                <div class="text-[10px] font-mono" style="color:${color}">${icon} ${label}</div>
+                ${duration ? `<div class="mt-1 text-[10px] text-slate-500">⏱️ ${duration}</div>` : ''}
+            </div>
+        </div>
+    </div>`;
+}
+
+function _renderBackgroundJobs(jobs) {
+    const pinned = jobs.filter(s => s.status === 'running' || s.status === 'failed');
+    const completed = jobs.filter(s => s.status !== 'running' && s.status !== 'failed');
+    const recent = completed.slice(0, 12);
+    const visibleIds = new Set([...pinned, ...recent].map(s => s.task_id));
+    const visible = jobs.filter(s => visibleIds.has(s.task_id));
+    const older = completed.slice(12);
+    return `<section>
+        <h3 class="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-sky-300">Фоновые задачи</h3>
+        <div class="space-y-2">${visible.map(_renderBackgroundJob).join('')}</div>
+        ${older.length ? `<details class="mt-3 rounded-lg border border-slate-800/70 bg-slate-950/20 p-2">
+            <summary class="cursor-pointer select-none text-[10px] text-slate-400 hover:text-slate-200">Показать старые задачи (${older.length})</summary>
+            <div class="mt-2 space-y-2">${older.map(_renderBackgroundJob).join('')}</div>
+        </details>` : ''}
+    </section>`;
+}
+
 async function _toggleTranscript(btn, sid) {
     const panel = btn.parentElement.querySelector('.sa-transcript-panel');
     if (!panel) return;
     if (!panel.classList.contains('hidden')) {
         panel.classList.add('hidden');
         btn.textContent = '📜 Транскрипт';
         return;
     }
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index b08fbadc5..b2d03ee85 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -182,21 +182,21 @@
           <h2 class="text-sm font-bold text-white">📊 Usage Analytics</h2>
           <button class="text-slate-400 hover:text-white text-lg" onclick="closeAnalyticsModal()">✕</button>
         </div>
         <div id="analytics-tabs" class="flex gap-1 mb-4"></div>
         <div id="analytics-body" class="flex-1 overflow-auto text-xs text-slate-300"></div>
       </div>
     </div>
 
-    <!-- Sub-agents Modal -->
+    <!-- Agent activity modal -->
     <div id="subagents-modal" class="fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm z-50 items-center justify-center hidden" onclick="if(event.target===this)closeSubagentsModal()">
       <div class="glass glow rounded-xl p-6 w-[90vw] max-w-3xl max-h-[85vh] flex flex-col">
         <div class="flex justify-between items-center mb-4">
-          <h2 class="text-sm font-bold text-white">🤖 Sub-agents · <span id="subagents-modal-agent" class="text-purple-300"></span></h2>
+          <h2 class="text-sm font-bold text-white">🤖 Agent activity · <span id="subagents-modal-agent" class="text-purple-300"></span></h2>
           <button class="text-slate-400 hover:text-white text-lg" onclick="closeSubagentsModal()">✕</button>
         </div>
         <div id="subagents-body" class="flex-1 overflow-auto text-xs text-slate-300"></div>
       </div>
     </div>
 
     {% if is_auth_enabled %}
     <!-- Client Info Modal -->
diff --git a/pyproject.toml b/pyproject.toml
index bfcc60acc..d26077f21 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,14 +1,14 @@
 [project]
 name = "orchestra"
 version = "0.1.0"
 requires-python = ">=3.12"
 dependencies = [
-    "claude-agent-sdk>=0.1.72",
+    "claude-agent-sdk>=0.2.111",
     "fastapi>=0.115,<1.0",
     "uvicorn[standard]>=0.34,<1.0",
     "jinja2>=3.1,<4.0",
     "mcp>=0.1,<2.0",
     "httpx>=0.27,<1.0",
     "telegramify-markdown>=1.1.3",
     "markdown>=3.10.2",
     "aiogram>=3.28,<4.0",
diff --git a/tests/test_backend_claude.py b/tests/test_backend_claude.py
index a05cd8cba..6b6087b57 100644
--- a/tests/test_backend_claude.py
+++ b/tests/test_backend_claude.py
@@ -1,15 +1,17 @@
 """Task #39 Fix 6 — ClaudeBackend cleans up client on connect/reconnect failure (no zombie CLI)."""
 
 import asyncio
 from unittest.mock import AsyncMock, patch
 
 import pytest
+from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
 
+import app.backend_claude as backend_claude
 from app.backend_claude import ClaudeBackend
 
 
 def _backend():
     return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")
 
 
 @pytest.mark.asyncio
@@ -43,8 +45,75 @@ async def test_reconnect_timeout_disconnects_client():
     client = AsyncMock()
     client.connect = AsyncMock(side_effect=TimeoutError("reconnect timed out"))
     client.disconnect = AsyncMock()
     b = _backend()
     with patch.object(b, "_make_client", return_value=client):
         with pytest.raises(TimeoutError):
             await b.reconnect()
     assert b._client is None
+
+
+@pytest.mark.asyncio
+async def test_interrupt_returns_true_on_control_ack():
+    client = AsyncMock()
+    client.interrupt = AsyncMock()
+    b = _backend()
+    b._client = client
+
+    assert await b.interrupt() is True
+    client.interrupt.assert_awaited_once()
+
+
+@pytest.mark.asyncio
+async def test_interrupt_is_bounded_when_control_ack_never_arrives(monkeypatch):
+    async def never_returns():
+        await asyncio.Event().wait()
+
+    client = AsyncMock()
+    client.interrupt = never_returns
+    b = _backend()
+    b._client = client
+    monkeypatch.setattr(backend_claude, "CLAUDE_INTERRUPT_TIMEOUT", 0.02, raising=False)
+
+    result = await asyncio.wait_for(b.interrupt(), timeout=0.2)
+
+    assert result is False
+
+
+def test_server_error_is_carried_into_terminal_turn_result():
+    b = _backend()
+
+    error_events = b._convert(AssistantMessage(
+        content=[TextBlock("API Error: Response stalled mid-stream.")],
+        model="claude-opus-4-8",
+        error="server_error",
+    ))
+    result_events = b._convert(ResultMessage(
+        subtype="result",
+        duration_ms=301_000,
+        duration_api_ms=301_000,
+        is_error=True,
+        num_turns=1,
+        session_id="sdk-server-error",
+        stop_reason="stop_sequence",
+        errors=[],
+    ))
+
+    assert error_events[-1].type == "error"
+    assert error_events[-1].metadata["model_error"] == "server_error"
+    turn_end = result_events[-1]
+    assert turn_end.type == "turn_end"
+    assert turn_end.metadata["ok"] is False
+    assert turn_end.metadata["model_error"] == "server_error"
+    assert turn_end.metadata["errors"] == ["server_error"]
+
+    next_result = b._convert(ResultMessage(
+        subtype="result",
+        duration_ms=10,
+        duration_api_ms=10,
+        is_error=False,
+        num_turns=1,
+        session_id="sdk-server-error",
+        stop_reason="stop_sequence",
+    ))[-1]
+    assert next_result.metadata["model_error"] == ""
+    assert next_result.metadata["errors"] == []
diff --git a/tests/test_backend_codex.py b/tests/test_backend_codex.py
index a943c5116..547c8e6da 100644
--- a/tests/test_backend_codex.py
+++ b/tests/test_backend_codex.py
@@ -2,16 +2,17 @@
 
 Regression net for the three bugs found in the codex-integration audit:
   BUG 1 — Sol/Terra/Luna missing from context/price dicts (worker got 258400 ctx, $0).
   BUG 2 — reasoning effort hardcoded, xhigh/max not in the accepted set.
   MCP   — per-worker MCP servers now injected via -c dotted-leaf overrides.
 """
 
 import json
+from types import SimpleNamespace
 
 import pytest
 
 from app.backend_codex import (
     CodexBackend,
     CODEX_CONTEXT_LIMITS,
     CODEX_TOKEN_PRICES,
     CODEX_REASONING_EFFORTS,
@@ -141,8 +142,36 @@ def test_toml_str_escapes():
 
 
 def test_codex_inherits_orchestra_proxy(monkeypatch):
     monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12343")
     monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:12343")
     env = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")._build_env()
     assert env["HTTPS_PROXY"] == "http://127.0.0.1:12343"
     assert env["HTTP_PROXY"] == "http://127.0.0.1:12343"
+
+
+@pytest.mark.asyncio
+async def test_thread_started_exposes_session_id_before_turn_completion():
+    class FakeStdout:
+        async def readline(self):
+            return b'{"type":"thread.started","thread_id":"thread-early"}\n'
+
+    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
+    backend._proc = SimpleNamespace(stdout=FakeStdout(), returncode=None)
+
+    events = backend.events()
+    event = await anext(events)
+    await events.aclose()
+
+    assert event.type == "status"
+    assert event.metadata["session_id"] == "thread-early"
+
+
+def test_is_alive_tracks_codex_process_state():
+    backend = CodexBackend(model="gpt-5.6-sol", cwd="/tmp")
+    assert backend.is_alive is False
+
+    backend._proc = SimpleNamespace(returncode=None)
+    assert backend.is_alive is True
+
+    backend._proc.returncode = 0
+    assert backend.is_alive is False
diff --git a/tests/test_session.py b/tests/test_session.py
index 11f5fc569..513b13a62 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -233,90 +233,235 @@ class TestStop:
                 send_task.cancel()
                 try:
                     await send_task
                 except (asyncio.CancelledError, Exception):
                     pass
 
         assert session.status == AgentStatus.IDLE
 
+    @pytest.mark.asyncio
+    async def test_interrupt_marks_idle_first_and_disconnects_on_missing_ack(self, session):
+        from app.session import AgentStatus
+
+        observed = {}
+
+        class InterruptBackend:
+            disconnected = False
+
+            async def interrupt(self):
+                observed["status"] = session.status
+                observed["lock"] = session._lifecycle_lock.locked()
+                return False
+
+            async def disconnect(self):
+                self.disconnected = True
+
+        backend = InterruptBackend()
+        session._backend = backend
+        session.status = AgentStatus.RUNNING
+        session._turn_start = 123.0
+
+        await session.interrupt()
+        await session._drain_persist()
+
+        assert observed == {"status": AgentStatus.IDLE, "lock": True}


## LATER FIX 42e0352e8b (50.1 days later): fix: fence stale retries and isolate dashboard recovery failures
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

fix: fence stale retries and isolate dashboard recovery failures


diff --git a/app/session.py b/app/session.py
index 165af7f81..2f1237e80 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1279,17 +1279,17 @@ class AgentSession:
         self._last_text_output = None
         self._turn_start = asyncio.get_event_loop().time()
         self._last_msg_time = self._turn_start
         self.status = AgentStatus.RUNNING
         self._persist()
 
     async def send(
         self, message: str | InjectedMessage, *, provenance: MessageProvenance,
-        delivery=None,
+        delivery=None, retry_generation: tuple[int, int] | None = None,
     ) -> None:
         if isinstance(message, InjectedMessage) and message.provenance != provenance:
             raise ValueError("injected message provenance mismatch")
         message_event_id = message.event_id if isinstance(message, InjectedMessage) else ""
         message = message.text if isinstance(message, InjectedMessage) else message
         original_user_message = message
         history_user_message = original_user_message
         if delivery is not None:
@@ -1302,16 +1302,26 @@ class AgentSession:
         if allow_running_delivery and self._compacting:
             return
         decision = None
         admitted_model = ""
         admitted_stop_gen = -1
 
         while True:
             await self._lifecycle_lock.acquire()
+            # Recheck after admission too: Stop or a newer turn can win while
+            # this sender is outside the lock waiting for quota data.
+            if retry_generation is not None and (
+                retry_generation != (self._turn_gen, self._turn_start_cancel_gen)
+                or self._manually_interrupted
+                or self.status != AgentStatus.IDLE
+                or self._compacting
+            ):
+                self._lifecycle_lock.release()
+                return
             if self._handoff_recovery_required:
                 self._lifecycle_lock.release()
                 raise RuntimeError(
                     "handoff_recovery_required: operator recovery is required before sends"
                 )
             if self._compacting or self.status == AgentStatus.RUNNING or self.is_orchestrator:
                 break
             if decision is None:
@@ -1346,22 +1356,22 @@ class AgentSession:
 
         try:
             if (
                 delivery is not None
                 and not allow_running_delivery
                 and (self._compacting or self.status == AgentStatus.RUNNING)
             ):
                 raise RuntimeError("initial delivery requires an idle session")
-        # Retry budgets belong to one logical request. A real new message resets both;
-        # each internal retry preserves only its own failure class.
-            if provenance.subtype != "rate_limit_retry":
+            # Both failure classes share the logical request: alternating upstream
+            # errors must not replenish each other's retry budget.
+            if provenance.subtype not in {"rate_limit_retry", "server_error_retry"}:
                 self._rate_limit_retries = 0
-            if provenance.subtype != "server_error_retry":
                 self._server_error_retries = 0
+            if provenance.subtype != "server_error_retry":
                 self._session_limit_hit = False
             self._safeguard_refusal = ""
 
             self._note_next_precompact_activity()
             capabilities = get_runtime(self.backend_type).capabilities
             if self._compacting:
                 if delivery is not None and allow_running_delivery:
                     return
@@ -2525,17 +2535,17 @@ class AgentSession:
             if "rate_limit" in event.content:
                 # Terminal subscription/usage limits — never retry
                 if self._session_limit_hit or _is_terminal_subscription_limit(event.content):
                     self._log("error", "⏳ subscription limit — ждём сброса квоты. НЕ ретраим")
                 elif self._rate_limit_retries < self.RATE_LIMIT_MAX_RETRIES:
                     self._rate_limit_retries += 1
                     delay = self.RATE_LIMIT_DELAY * self._rate_limit_retries
                     self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
-                    self._spawn_bg(self._rate_limit_retry(delay))
+                    self._spawn_bg(self._rate_limit_retry(delay, self._turn_gen))
                 else:
                     self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
             else:
                 self._log("error", event.content)
         elif event.type == "subagent_start":
             self._log("subagent_start", event.content)
             self._persist_subagent(event.metadata)
         elif event.type == "subagent_progress":
@@ -3204,69 +3214,84 @@ class AgentSession:
     async def _notify_scope_running(self) -> None:
         if on_scope_running is None:
             return
         try:
             await on_scope_running(self)
         except Exception as e:
             logger.warning(f"[{self.name}] TG scope-running notify failed: {e}")
 
-    async def _rate_limit_retry(self, delay: int) -> None:
+    async def _rate_limit_retry(self, delay: int, expected_turn_gen: int) -> None:
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
+        if self._manually_interrupted or self._turn_gen != expected_turn_gen:
+            return
         try:
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="rate_limit_retry",
             )
             await self.send(
                 "[system] Retrying after rate limit. Continue where you left off.",
                 provenance=provenance,
+                retry_generation=generation,
             )
-            logger.info(f"[{self.name}] rate-limit retry after {delay}s")
         except DrainingRefused as refusal:
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self._log("status", f"drain: {refusal}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
             self._queue_drain_fact("rate-limit-retry", "повтор после rate limit срезан")
         except Exception as e:
             logger.warning(f"[{self.name}] rate-limit retry failed: {e}")
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _retry_after_server_error(self, delay: int, expected_turn_gen: int) -> None:
         """Resume through a fresh SDK transport after an upstream stream failure."""
+        generation = (expected_turn_gen, self._turn_start_cancel_gen)
         await asyncio.sleep(delay)
         try:
             async with self._lifecycle_lock:
                 # A real user message already started a newer turn; it supersedes this
                 # automatic retry and must not be duplicated.
-                if self._turn_gen != expected_turn_gen or self.status != AgentStatus.IDLE:
+                if (self._manually_interrupted
+                        or self._turn_gen != expected_turn_gen
+                        or self.status != AgentStatus.IDLE
+                        or self._compacting):
                     return
                 await self._disconnect_backend()
             provenance = MessageProvenance(
                 origin="system", senders=("system",), subtype="server_error_retry",
             )
             await self.send(
                 "[system] Retrying after transient server error. Continue where you "
                 "left off. Do not repeat completed research; execute the pending "
                 "deliverable now.",
                 provenance=provenance,
+                retry_generation=generation,
             )
-            logger.info(f"[{self.name}] server-error retry after {delay}s")
         except DrainingRefused as refusal:
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self._log("status", f"drain: {refusal}")
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
             self._queue_drain_fact(
                 "server-error-retry", "повтор после сбоя апстрима срезан",
             )
         except Exception as e:
             logger.warning(f"[{self.name}] server-error retry failed: {e}")
+            if generation != (self._turn_gen, self._turn_start_cancel_gen):
+                return
             self.status = AgentStatus.IDLE
             self._persist()
             self._turns.publish_turn_finished()
 
     async def _auto_continue(self) -> None:
         await asyncio.sleep(1)
         try:
             provenance = MessageProvenance(
diff --git a/app/static/js/connection.js b/app/static/js/connection.js
index a87e38f97..adc30ff91 100644
--- a/app/static/js/connection.js
+++ b/app/static/js/connection.js
@@ -227,33 +227,53 @@ window.Connection = (() => {
             set('online');
         } else render();
     }
 
     async function recover() {
         if (recovering) return;
         recovering = true;
         const reason = state.reason;
-        set('recovering', {reason});
-        restartPending = false;
-        const restartBtn = document.getElementById('restart-btn');
-        if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
-        resetChatTransientState();
-        const calls = [
-            selectedAgent && currentScope ? _showChatFor(selectedAgent, currentScope) : null,
-            refreshSessions(), loadOrchestrators(), loadModels(), refreshOpenFolders(),
-            fetchUsage(), window.QuotaPanel?.fetch?.(),
-        ].filter(Boolean);
         try {
-            await Promise.allSettled(calls);
+            set('recovering', {reason});
+            restartPending = false;
+            const restartBtn = document.getElementById('restart-btn');
+            if (restartBtn) { restartBtn.disabled = false; restartBtn.textContent = '⟳'; }
+            // Defer invocation as well as awaiting: one synchronous renderer error
+            // must not prevent the other surfaces from recovering.
+            const refreshes = [
+                ['chat', () => {
+                    resetChatTransientState();
+                    return selectedAgent && currentScope
+                        ? _showChatFor(selectedAgent, currentScope) : null;
+                }],
+                ['sessions', () => refreshSessions()],
+                ['orchestrators', () => loadOrchestrators()],
+                ['models', () => loadModels()],
+                ['files', () => refreshOpenFolders()],
+                ['usage', () => fetchUsage()],
+                ['quota', () => window.QuotaPanel?.fetch?.()],
+            ];
+            const results = await Promise.allSettled(
+                refreshes.map(([, refresh]) => Promise.resolve().then(refresh)),
+            );
+            const errors = [];
+            results.forEach((result, index) => {
+                const key = `recovery/${refreshes[index][0]}`;
+                if (result.status === 'rejected') {
+                    state.failures.set(key, {error: result.reason, at: Date.now()});
+                    errors.push(`${refreshes[index][0]}: ${String(result.reason)}`);
+                } else state.failures.delete(key);
+            });
             wasDown = false;
             if (state.failures.size || state.stale.size) {
                 set('degraded', {
                     reason: 'partial_recovery',
                     path: state.failures.keys().next().value || '',
+                    message: errors.length ? `Не удалось обновить: ${errors.join('; ')}` : '',
                 });
                 return;
             }
             const flash = reason === 'restart'
                 ? 'Orchestra перезапустилась · данные обновлены'
                 : 'Связь восстановлена · данные обновлены';
             set('online', {reason: '', path: '', flash});
             state.flashTimer = setTimeout(() => {
diff --git a/tests/test_connection_recovery.py b/tests/test_connection_recovery.py
new file mode 100644
index 000000000..6aec0765f
--- /dev/null
+++ b/tests/test_connection_recovery.py
@@ -0,0 +1,60 @@
+"""Recovery errors cannot strand the dashboard or prevent other refreshes."""
+
+from pathlib import Path
+
+import pytest
+from playwright.sync_api import sync_playwright
+
+
+@pytest.fixture(scope="module")
+def recovery_browser():
+    with sync_playwright() as playwright:
+        browser = playwright.chromium.launch(headless=True)
+        yield browser
+        browser.close()
+
+
+@pytest.mark.parametrize("failure", ["sync", "async", "chat_reset"])
+def test_recovery_isolates_failure_and_can_run_again(recovery_browser, failure):
+    page = recovery_browser.new_page()
+    try:
+        page.set_content("<body><div id='connection-banner'></div></body>")
+        page.evaluate("""() => {
+            window.escHtml = text => String(text);
+            window.selectedAgent = 'worker'; window.currentScope = '/scope';
+            window.resetChatTransientState = () => {};
+            window._showChatFor = async () => {};
+            window.refreshSessions = async () => {};
+            window.loadOrchestrators = async () => {};
+            window.loadModels = async () => {};
+            window.refreshOpenFolders = async () => {};
+            window.fetchUsage = async () => {};
+        }""")
+        page.add_script_tag(path=str(
+            Path(__file__).parents[1] / "app/static/js/connection.js"
+        ))
+        result = page.evaluate("""async failure => {
+            const calls = [];
+            refreshSessions = async () => { calls.push('sessions'); };
+            refreshOpenFolders = async () => { calls.push('files'); };
+            const broken = () => { throw new Error('refresh exploded'); };
+            if (failure === 'sync') fetchUsage = broken;
+            if (failure === 'async') fetchUsage = async () => broken();
+            if (failure === 'chat_reset') resetChatTransientState = broken;
+            let escaped = '';
+            try { await Connection.recover(); } catch (error) { escaped = error.message; }
+            const first = {phase: Connection.state.phase, calls: [...calls],
+                banner: document.getElementById('connection-banner').textContent};
+            fetchUsage = async () => {};
+            resetChatTransientState = () => {};
+            await Connection.recover();
+            return {escaped, first, calls, phase: Connection.state.phase};
+        }""", failure)
+        assert result["escaped"] == ""
+        assert result["first"]["phase"] == "degraded"
+        assert result["first"]["calls"] == ["sessions", "files"]
+        assert "refresh exploded" in result["first"]["banner"]
+        assert result["calls"] == ["sessions", "files", "sessions", "files"]
+        assert result["phase"] == "online"
+    finally:
+        page.close()
diff --git a/tests/test_hot_apply.py b/tests/test_hot_apply.py
index 283046dc3..1ea2b9940 100644
--- a/tests/test_hot_apply.py
+++ b/tests/test_hot_apply.py
@@ -296,17 +296,17 @@ async def test_t2_internal_starter_queues_a_fact_instead_of_starting(
     _gate(manager)()
     try:
         with patch.object(s, "_make_backend", return_value=backend):
             # у каждого стартера свои аргументы; задержки нулевые, чтобы тест
             # не подрабатывал измерением времени
             args = {
                 "_flush_pending": (),
                 "_auto_continue": (),
-                "_rate_limit_retry": (0,),
+                "_rate_limit_retry": (0, s._turn_gen),
                 "_retry_after_server_error": (0, s._turn_gen),
             }[starter]
             await asyncio.wait_for(getattr(s, starter)(*args), timeout=10)
     finally:
         manager.end_drain()
 
     assert s.status is AgentStatus.IDLE, "ход не начат"
     assert backend.sent == [], "в бэкенд ничего не ушло"
diff --git a/tests/test_session.py b/tests/test_session.py
index 698b0fe9c..a4c719bbd 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -3129,16 +3129,110 @@ class TestRateLimitClassification:
         session.send.reset_mock()
         session._turn_gen = 5
 
         await session._retry_after_server_error(0, 4)
 
         session._disconnect_backend.assert_not_awaited()
         session.send.assert_not_awaited()
 
+    @pytest.mark.asyncio
+    @pytest.mark.parametrize("kind", ["server_error", "rate_limit"])
+    async def test_manual_stop_cancels_waiting_retry(self, session, monkeypatch, kind):
+        from app.session import AgentStatus
+
+        sleeping = asyncio.Event()
+        resume = asyncio.Event()
+
+        async def controlled_sleep(_delay):
+            sleeping.set()
+            await resume.wait()
+
+        monkeypatch.setattr("app.session.asyncio.sleep", controlled_sleep)
+        session.status = AgentStatus.IDLE
+        session._disconnect_backend = AsyncMock()
+        session.send = AsyncMock()
+        coroutine = (session._retry_after_server_error(5, session._turn_gen)
+                     if kind == "server_error" else session._rate_limit_retry(5, session._turn_gen))
+        retry = asyncio.create_task(coroutine)
+        try:
+            await sleeping.wait()
+            await session.interrupt()
+            resume.set()
+            await retry
+            session.send.assert_not_awaited()
+            session._disconnect_backend.assert_not_awaited()
+        finally:
+            resume.set()
+            retry.cancel()
+            await asyncio.gather(retry, return_exceptions=True)
+
+
+class TestRetryAdmissionRaces:
+    @pytest.mark.asyncio
+    async def test_alternating_retry_types_preserve_both_budgets(self, session):
+        from app.session import AgentStatus
+
+        backend = _MockBackend()
+        session._ensure_backend = AsyncMock(return_value=backend)
+        session._attach_pending_facts = lambda message: (message, ())
+        session._ack_pending_facts = lambda _keys: None


## LATER FIX 6057d1e11d (80.2 days later): V-706: #V-706: fix session API and delivery lifecycle
lines of origin it changed/deleted: 4
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