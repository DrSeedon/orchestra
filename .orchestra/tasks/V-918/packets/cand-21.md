# Candidate cand-21

## ORIGIN commit 3ef921eaca (2026-07-03): feat: full sub-agent telemetry — subagents table + transcript endpoints
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index b5408e17f..b1d797a58 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -235,16 +235,28 @@ class ClaudeBackend:
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend reconnect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
+    @staticmethod
+    def _task_usage(usage) -> dict:
+        """Extract TaskUsage (total_tokens/tool_uses/duration_ms) — TypedDict or obj."""
+        if not usage:
+            return {}
+        get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
+        return {
+            "total_tokens": get("total_tokens", 0) or 0,
+            "tool_uses": get("tool_uses", 0) or 0,
+            "duration_ms": get("duration_ms", 0) or 0,
+        }
+
     @staticmethod
     def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
         """Mark an event as belonging to a sub-agent so the UI nests it.
 
         sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
         the type is preserved (tool_use stays tool_use) — the frontend groups by
         subagent_id, not by a renamed type."""
         if sub_id is not None:
@@ -303,34 +315,48 @@ class ClaudeBackend:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                         events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
         elif isinstance(msg, TaskStartedMessage):
             desc = getattr(msg, "description", "") or ""
             task_type = getattr(msg, "task_type", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
             events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}",
-                                     metadata={"subagent_id": task_id}))
+                                     metadata={"subagent_id": task_id, "phase": "start",
+                                               "description": desc, "task_type": task_type,
+                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "tool_use_id": getattr(msg, "tool_use_id", "") or ""}))
 
         elif isinstance(msg, TaskProgressMessage):
             desc = getattr(msg, "description", "") or ""
             last_tool = getattr(msg, "last_tool_name", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
-            usage = getattr(msg, "usage", None)
-            tokens = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0
-            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}",
-                                     metadata={"subagent_id": task_id}))
+            u = self._task_usage(getattr(msg, "usage", None))
+            events.append(AgentEvent("subagent_progress",
+                                     f"{desc} | tool={last_tool} | tokens={u.get('total_tokens', 0)}",
+                                     metadata={"subagent_id": task_id, "phase": "progress",
+                                               "description": desc, "last_tool_name": last_tool,
+                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               **u}))
 
         elif isinstance(msg, TaskNotificationMessage):
             desc = getattr(msg, "description", "") or ""
             status = getattr(msg, "status", "") or ""
             summary = getattr(msg, "summary", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
+            output_file = getattr(msg, "output_file", "") or ""
+            u = self._task_usage(getattr(msg, "usage", None))
+            data = getattr(msg, "data", None)
             events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}",
-                                     metadata={"subagent_id": task_id}))
+                                     metadata={"subagent_id": task_id, "phase": "end",
+                                               "description": desc, "status": status,
+                                               "summary": summary, "output_file": output_file,
+                                               "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "raw_json": _json.dumps(data, ensure_ascii=False) if data else "",
+                                               **u}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
 
             is_err = bool(getattr(msg, "is_error", False))
diff --git a/app/db.py b/app/db.py
index 336208ba6..4ffa97b77 100644
--- a/app/db.py
+++ b/app/db.py
@@ -73,16 +73,38 @@ def init_db() -> None:
                 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                 ts TEXT NOT NULL,
                 type TEXT NOT NULL,
                 content TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
             CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);
 
+            CREATE TABLE IF NOT EXISTS subagents (
+                id INTEGER PRIMARY KEY AUTOINCREMENT,
+                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
+                task_id TEXT NOT NULL,
+                sdk_session_id TEXT DEFAULT '',
+                tool_use_id TEXT DEFAULT '',
+                description TEXT DEFAULT '',
+                task_type TEXT DEFAULT '',
+                status TEXT DEFAULT 'running',
+                total_tokens INTEGER DEFAULT 0,
+                tool_uses INTEGER DEFAULT 0,
+                duration_ms INTEGER DEFAULT 0,
+                last_tool_name TEXT DEFAULT '',
+                output_file TEXT DEFAULT '',
+                summary TEXT DEFAULT '',
+                raw_json TEXT DEFAULT '',
+                started_at TEXT NOT NULL,
+                ended_at TEXT,
+                UNIQUE(session_id, task_id)
+            );
+            CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);
+
             CREATE TABLE IF NOT EXISTS inbox (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                 sender TEXT NOT NULL,
                 message TEXT NOT NULL,
                 status TEXT DEFAULT 'pending',
                 created_at TEXT NOT NULL
             );
@@ -655,16 +677,70 @@ def add_log(session_id: str, ts: datetime, type: str, content: str) -> int:
     with _conn() as c:
         cur = c.execute(
             "INSERT INTO logs (session_id, ts, type, content) VALUES (?, ?, ?, ?)",
             (session_id, ts.isoformat(), type, content),
         )
         return cur.lastrowid
 
 
+# Sub-agent telemetry columns that upsert may set. Text cols use NULLIF-COALESCE
+# (empty from a progress event must NOT wipe a value set by start/end). Numeric
+# cols take the incoming value when > 0 (TaskUsage is cumulative → latest wins,
+# never summed — session total already counts subagents, see backend_claude).
+_SA_TEXT = ("sdk_session_id", "tool_use_id", "description", "task_type",
+            "status", "last_tool_name", "output_file", "summary", "raw_json", "ended_at")
+_SA_NUM = ("total_tokens", "tool_uses", "duration_ms")
+
+
+def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
+    """Insert or update one sub-agent row (keyed by session_id+task_id).
+
+    start creates the row; progress/end update only the fields they carry.
+    Empty text / zero numbers never overwrite an existing value.
+    """
+    cols = ["session_id", "task_id", "started_at"]
+    vals = [session_id, task_id, datetime.now(timezone.utc).isoformat()]
+    updates = []
+    for k in _SA_TEXT:
+        if k in fields and fields[k] is not None:
+            cols.append(k); vals.append(fields[k])
+            updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
+    for k in _SA_NUM:
+        if k in fields and fields[k]:
+            cols.append(k); vals.append(int(fields[k]))
+            updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
+    placeholders = ", ".join("?" for _ in cols)
+    set_clause = ", ".join(updates) if updates else "task_id=task_id"
+    with _conn() as c:
+        c.execute(
+            f"INSERT INTO subagents ({', '.join(cols)}) VALUES ({placeholders}) "
+            f"ON CONFLICT(session_id, task_id) DO UPDATE SET {set_clause}",
+            vals,
+        )
+
+
+def get_subagents(session_id: str) -> list[dict]:
+    with _conn() as c:
+        rows = c.execute(
+            "SELECT * FROM subagents WHERE session_id = ? ORDER BY started_at ASC",
+            (session_id,),
+        ).fetchall()
+        return [dict(r) for r in rows]
+
+
+def get_subagent(session_id: str, task_id: str) -> dict | None:
+    with _conn() as c:
+        row = c.execute(
+            "SELECT * FROM subagents WHERE session_id = ? AND task_id = ?",
+            (session_id, task_id),
+        ).fetchone()
+        return dict(row) if row else None
+
+
 def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
     c = conn or _conn()
     try:
         if after_id > 0:
             rows = c.execute(
                 "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                 (session_id, after_id, limit),
             ).fetchall()
diff --git a/app/events.py b/app/events.py
index d98f46a8d..b8f7ae22d 100644
--- a/app/events.py
+++ b/app/events.py
@@ -13,11 +13,12 @@ class AgentEvent:
 # "text"              — agent text output
 # "thinking"          — agent reasoning/thinking output
 # "tool_use"          — tool invocation (content = "tool_name: input_summary")
 # "tool_result"       — tool output
 # "file_change"       — file edit (content = "add /path" or "update /path")
 # "turn_end"          — turn completed (metadata: session_id, cost_usd, input_tokens, context_pct, ok, stop_reason, ...)
 # "error"             — error message
 # "status"            — lifecycle event
-# "subagent_start"    — sub-agent spawned
-# "subagent_progress" — sub-agent working
-# "subagent_end"      — sub-agent finished
+# "subagent_start"    — sub-agent spawned    (metadata: subagent_id, phase, description, task_type, sdk_session_id, tool_use_id)
+# "subagent_progress" — sub-agent working     (metadata: + last_tool_name, total_tokens, tool_uses, duration_ms)
+# "subagent_end"      — sub-agent finished    (metadata: + status, summary, output_file, raw_json, usage)
+# "subagent_stream"   — sub-agent live text   (metadata: subagent_id) — broker only, ephemeral
diff --git a/app/main.py b/app/main.py
index f218a9d81..dd8a3be3d 100644
--- a/app/main.py
+++ b/app/main.py
@@ -65,22 +65,24 @@ app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
 from app.routes.tm import router as tm_router
 from app.routes.bg import router as bg_router
 from app.routes.proxy import router as proxy_router
 from app.routes.sessions import router as sessions_router
 from app.routes.system import router as system_router
 from app.routes.tg import router as tg_router
+from app.routes.subagent import router as subagent_router
 app.include_router(tm_router)
 app.include_router(bg_router)
 app.include_router(proxy_router)
 app.include_router(sessions_router)
 app.include_router(system_router)
 app.include_router(tg_router)
+app.include_router(subagent_router)
 
 
 @app.exception_handler(Exception)
 async def global_exception_handler(request: Request, exc: Exception):
     import traceback
     tb = traceback.format_exc()
     logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb}")
     return JSONResponse({"error": f"Internal: {exc}"}, status_code=500)
diff --git a/app/routes/subagent.py b/app/routes/subagent.py
new file mode 100644
index 000000000..f4f68030c
--- /dev/null
+++ b/app/routes/subagent.py
@@ -0,0 +1,72 @@
+"""Sub-agent telemetry + transcript routes.
+
+Telemetry (tokens/summary/output_file/status) comes from the DB `subagents`
+table (populated from Task* SDK messages). Full transcripts are read lazily
+from the SDK's JSONL store via list_subagents / get_subagent_messages — NOT
+duplicated in our DB. agent_id (SDK file id) != task_id (Task message id), so
+transcript listing is independent of the telemetry table.
+"""
+
+import logging
+import re
+
+from fastapi import APIRouter
+from fastapi.responses import JSONResponse
+
+from app.db import get_subagents, get_session
+
+logger = logging.getLogger("orchestra.subagent")
+
+router = APIRouter(tags=["subagent"])
+
+_SAFE_ID = re.compile(r"^[\w-]+$")  # agent_id goes into a filename — no path traversal
+
+
+@router.get("/api/subagents/{session_id}")
+async def subagents_list(session_id: str):
+    """Telemetry rows for a session's sub-agents (from Task* messages)."""
+    return {"subagents": get_subagents(session_id)}
+
+
+@router.get("/api/subagent-transcripts/{session_id}")
+async def subagent_transcript_ids(session_id: str):
+    """SDK agent_ids of sub-agents whose transcripts exist for this session."""
+    sess = get_session(session_id)
+    if not sess:
+        return JSONResponse({"error": "session not found"}, status_code=404)
+    sdk_id = sess.get("session_id") or ""
+    if not sdk_id:
+        return {"agent_ids": [], "note": "no sdk_session_id yet"}
+    from claude_agent_sdk import list_subagents
+    try:
+        agent_ids = list_subagents(sdk_id, sess.get("cwd") or None)
+    except Exception as e:
+        logger.warning(f"list_subagents failed: {e}")
+        return {"agent_ids": [], "error": str(e)}
+    return {"agent_ids": agent_ids, "sdk_session_id": sdk_id}
+
+
+@router.get("/api/subagent-transcript/{session_id}/{agent_id}")
+async def subagent_transcript(session_id: str, agent_id: str, limit: int = 200, offset: int = 0):
+    """Full conversation of one sub-agent (lazy read from SDK JSONL store)."""
+    if not _SAFE_ID.match(agent_id):
+        return JSONResponse({"error": "invalid agent_id"}, status_code=400)
+    sess = get_session(session_id)
+    if not sess:
+        return JSONResponse({"error": "session not found"}, status_code=404)
+    sdk_id = sess.get("session_id") or ""
+    if not sdk_id:
+        return {"messages": [], "note": "no sdk_session_id yet"}
+    from claude_agent_sdk import get_subagent_messages
+    try:
+        msgs = get_subagent_messages(sdk_id, agent_id, sess.get("cwd") or None,
+                                     limit=limit, offset=offset)
+    except Exception as e:
+        logger.warning(f"get_subagent_messages failed: {e}")
+        return {"messages": [], "error": str(e)}
+    out = []
+    for m in msgs:
+        content = m.message.get("content") if isinstance(m.message, dict) else m.message
+        out.append({"type": m.type, "content": content,
+                    "parent_tool_use_id": getattr(m, "parent_tool_use_id", None)})
+    return {"messages": out, "count": len(out)}
diff --git a/app/session.py b/app/session.py
index 75e7751d0..937d58907 100644
--- a/app/session.py
+++ b/app/session.py
@@ -575,20 +575,23 @@ class AgentSession:
                     self._log("status", f"⏳ rate limit (Anthropic сервер) — повтор через {delay}s ({self._rate_limit_retries}/{self.RATE_LIMIT_MAX_RETRIES})")
                     self._spawn_bg(self._rate_limit_retry(delay))
                 else:
                     self._log("error", f"rate limit — gave up after {self.RATE_LIMIT_MAX_RETRIES} retries")
             else:
                 self._log("error", event.content)
         elif event.type == "subagent_start":
             self._log("subagent_start", event.content)
+            self._persist_subagent(event.metadata)
         elif event.type == "subagent_progress":
             self._log("subagent_progress", event.content)
+            self._persist_subagent(event.metadata)
         elif event.type == "subagent_end":
             self._log("subagent_end", event.content)
+            self._persist_subagent(event.metadata, ended=True)
         elif event.type == "status":
             self._log("status", event.content)
 
     async def _flush_pending(self) -> None:
         # Brief delay: let the just-finished turn fully settle (persist, hibernate schedule)
         # before starting the next one — avoids nested lock acquisition from the same coroutine
         await asyncio.sleep(0.3)
         if self._compacting:
@@ -964,16 +967,36 @@ class AgentSession:
     async def _drain_persist(self) -> None:
         if self._persist_task and not self._persist_task.done():
             await asyncio.gather(self._persist_task, return_exceptions=True)
 
     def _log(self, type: str, content: str) -> None:
         # Fire-and-forget on dedicated DB pool — keeps event loop non-blocking for log-heavy turns
         asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)
 
+    def _persist_subagent(self, meta: dict, ended: bool = False) -> None:
+        """Upsert sub-agent telemetry from a Task* event. Fire-and-forget.
+
+        Only the fields the event carries are passed — subagent_upsert's
+        NULLIF-COALESCE keeps prior values, so progress never wipes start's data.
+        """
+        task_id = meta.get("subagent_id")
+        if not task_id:
+            return
+        fields = {k: meta[k] for k in (
+            "sdk_session_id", "tool_use_id", "description", "task_type", "status",
+            "last_tool_name", "output_file", "summary", "raw_json",
+            "total_tokens", "tool_uses", "duration_ms",
+        ) if k in meta}
+        if ended:
+            fields["ended_at"] = datetime.now(timezone.utc).isoformat()
+        from app.db import subagent_upsert
+        asyncio.get_event_loop().run_in_executor(
+            _db_executor(), lambda: subagent_upsert(self.id, task_id, **fields))
+
     def _to_db_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
             "model": self.model, "system_prompt": self.system_prompt,
             "status": self.status.value, "session_id": self.session_id,
             "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
             "context_cost": self._context_cost,
             "worktree_path": self.worktree_path,
diff --git a/tests/test_subagent_routes.py b/tests/test_subagent_routes.py
new file mode 100644
index 000000000..ecf3bebd7
--- /dev/null
+++ b/tests/test_subagent_routes.py
@@ -0,0 +1,60 @@
+"""Sub-agent transcript endpoints: telemetry list, transcript ids, transcript,
+path-traversal guard."""
+
+import pytest
+
+from app.routes import subagent as sr
+
+
+@pytest.mark.asyncio
+async def test_transcript_rejects_path_traversal():
+    for bad in ("../../etc/passwd", "a/b", "a.b", "..", "x/../y"):
+        r = await sr.subagent_transcript("sess-1", bad)
+        assert r.status_code == 400
+
+
+@pytest.mark.asyncio
+async def test_transcript_ids_missing_session(monkeypatch):
+    monkeypatch.setattr(sr, "get_session", lambda sid: None)
+    r = await sr.subagent_transcript_ids("nope")
+    assert r.status_code == 404
+
+
+@pytest.mark.asyncio
+async def test_transcript_ids_no_sdk_session(monkeypatch):
+    monkeypatch.setattr(sr, "get_session", lambda sid: {"session_id": "", "cwd": "/c"})
+    r = await sr.subagent_transcript_ids("sess-1")
+    assert r["agent_ids"] == []
+
+
+@pytest.mark.asyncio
+async def test_transcript_reads_messages(monkeypatch):
+    monkeypatch.setattr(sr, "get_session",
+                        lambda sid: {"session_id": "550e8400-e29b-41d4-a716-446655440000", "cwd": "/c"})
+
+    class _Msg:
+        type = "user"
+        message = {"content": "hello from subagent"}
+        parent_tool_use_id = None
+
+    import claude_agent_sdk
+    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages",
+                        lambda *a, **k: [_Msg()])
+    r = await sr.subagent_transcript("sess-1", "ae795e652a2bbf63a")
+    assert r["count"] == 1
+    assert r["messages"][0]["content"] == "hello from subagent"
+
+
+@pytest.mark.asyncio
+async def test_transcript_sdk_error_graceful(monkeypatch):
+    monkeypatch.setattr(sr, "get_session",
+                        lambda sid: {"session_id": "550e8400-e29b-41d4-a716-446655440000", "cwd": "/c"})
+    import claude_agent_sdk
+
+    def boom(*a, **k):
+        raise RuntimeError("store unavailable")
+
+    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages", boom)
+    r = await sr.subagent_transcript("sess-1", "ae795e652a2bbf63a")
+    assert r["messages"] == []
+    assert "error" in r
diff --git a/tests/test_subagents.py b/tests/test_subagents.py
new file mode 100644
index 000000000..48e5e5f0f
--- /dev/null
+++ b/tests/test_subagents.py
@@ -0,0 +1,104 @@
+"""Sub-agent telemetry: upsert (start→progress→end), no-wipe, latest-tokens."""
+
+from datetime import datetime, timezone
+
+import pytest
+
+
+@pytest.fixture
+def db(tmp_path, monkeypatch):
+    db_path = tmp_path / "test.db"
+    monkeypatch.setattr("app.db.DB_PATH", db_path)
+    from app.db import init_db, save_session
+    init_db()
+    save_session({
+        "id": "sess-1", "name": "w", "scope": "/s", "cwd": "/c",
+        "model": "claude-sonnet-5[1m]", "system_prompt": "",
+        "status": "running", "session_id": "550e8400-e29b-41d4-a716-446655440000",
+        "cost_usd": 0.0, "worktree_path": "/w", "branch": "b",
+        "is_orchestrator": False, "color": "#fff",
+        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
+    })
+    return db_path
+
+
+def test_start_creates_row(db):
+    from app.db import subagent_upsert, get_subagents
+    subagent_upsert("sess-1", "task-a", description="Explore X", task_type="Explore",
+                    status="running", sdk_session_id="550e8400-e29b-41d4-a716-446655440000")
+    rows = get_subagents("sess-1")
+    assert len(rows) == 1
+    assert rows[0]["task_id"] == "task-a"
+    assert rows[0]["description"] == "Explore X"
+    assert rows[0]["status"] == "running"
+    assert rows[0]["sdk_session_id"] == "550e8400-e29b-41d4-a716-446655440000"
+
+
+def test_progress_updates_tokens_without_wiping_desc(db):
+    from app.db import subagent_upsert, get_subagent
+    subagent_upsert("sess-1", "task-a", description="Explore X", task_type="Explore")
+    # progress carries tokens + last_tool but empty description
+    subagent_upsert("sess-1", "task-a", description="", last_tool_name="Bash",
+                    total_tokens=1500, tool_uses=3, duration_ms=4200)
+    sa = get_subagent("sess-1", "task-a")
+    assert sa["description"] == "Explore X"  # NOT wiped by empty progress
+    assert sa["last_tool_name"] == "Bash"
+    assert sa["total_tokens"] == 1500
+    assert sa["tool_uses"] == 3
+
+
+def test_tokens_take_latest_max_not_summed(db):
+    from app.db import subagent_upsert, get_subagent
+    subagent_upsert("sess-1", "task-a", description="X")
+    subagent_upsert("sess-1", "task-a", total_tokens=1000)
+    subagent_upsert("sess-1", "task-a", total_tokens=2500)  # cumulative → latest
+    sa = get_subagent("sess-1", "task-a")
+    assert sa["total_tokens"] == 2500  # max/latest, NOT 3500 (no double-count)
+
+
+def test_end_sets_summary_output_status(db):
+    from app.db import subagent_upsert, get_subagent
+    subagent_upsert("sess-1", "task-a", description="X")
+    subagent_upsert("sess-1", "task-a", total_tokens=900)
+    subagent_upsert("sess-1", "task-a", status="completed", summary="Found 3 files",
+                    output_file="/tmp/out.md", total_tokens=1200,
+                    ended_at=datetime.now(timezone.utc).isoformat())
+    sa = get_subagent("sess-1", "task-a")
+    assert sa["status"] == "completed"
+    assert sa["summary"] == "Found 3 files"
+    assert sa["output_file"] == "/tmp/out.md"
+    assert sa["total_tokens"] == 1200
+    assert sa["ended_at"]
+
+
+def test_two_subagents_same_session_distinct(db):
+    from app.db import subagent_upsert, get_subagents
+    subagent_upsert("sess-1", "task-a", description="A")
+    subagent_upsert("sess-1", "task-b", description="B")
+    rows = get_subagents("sess-1")
+    assert {r["task_id"] for r in rows} == {"task-a", "task-b"}
+
+
+def test_get_subagent_missing_returns_none(db):
+    from app.db import get_subagent
+    assert get_subagent("sess-1", "nope") is None
+
+
+def test_concurrent_upserts_no_data_loss(db):
+    # fire-and-forget upserts run on a thread pool → simulate the race
+    import threading
+    from app.db import subagent_upsert, get_subagent
+    subagent_upsert("sess-1", "task-a", description="X", status="running")
+
+    def worker(n):
+        subagent_upsert("sess-1", "task-a", total_tokens=n * 100, last_tool_name=f"t{n}")
+
+    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 11)]
+    for t in threads:
+        t.start()
+    for t in threads:
+        t.join()
+    sa = get_subagent("sess-1", "task-a")
+    assert sa["total_tokens"] == 1000   # MAX wins, not summed (no double-count)
+    assert sa["description"] == "X"     # NULLIF-COALESCE: not wiped by race
+    assert sa["status"] == "running"


## LATER FIX 3b2b2415a2 (14.2 days later): fix: correlate subagent lifecycle events
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

fix: correlate subagent lifecycle events


diff --git a/app/backend_claude.py b/app/backend_claude.py
index 57e4e17c5..834d369fb 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -109,16 +109,22 @@ class ClaudeBackend:
         # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
         self._inherit_claude_md = inherit_claude_md
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
         self._effort = effort
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
         self._pending_model_error = ""
+        # SDK content events point at parent tool_use_id, while Task* lifecycle
+        # messages use task_id. Keep the bridge so live output and persisted
+        # lifecycle records address the same UI card.
+        self._subagent_tool_to_task: dict[str, str] = {}
+        self._subagent_descriptions: dict[str, str] = {}
+        self._subagent_types: dict[str, str] = {}
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     def _make_client(self) -> ClaudeSDKClient:
         import os
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
@@ -272,16 +278,24 @@ class ClaudeBackend:
             return {}
         get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
         return {
             "total_tokens": get("total_tokens", 0) or 0,
             "tool_uses": get("tool_uses", 0) or 0,
             "duration_ms": get("duration_ms", 0) or 0,
         }
 
+    def _resolve_subagent_id(self, parent_tool_use_id):
+        if parent_tool_use_id is None:
+            return None
+        return self._subagent_tool_to_task.get(
+            str(parent_tool_use_id),
+            str(parent_tool_use_id),
+        )
+
     @staticmethod
     def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
         """Mark an event as belonging to a sub-agent so the UI nests it.
 
         sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
         the type is preserved (tool_use stays tool_use) — the frontend groups by
         subagent_id, not by a renamed type."""
         if sub_id is not None:
@@ -298,27 +312,29 @@ class ClaudeBackend:
             if ev.get("type") != "content_block_delta":
                 return events
             delta = ev.get("delta") or {}
             if delta.get("type") != "text_delta":
                 return events
             text = delta.get("text") or ""
             if not text:
                 return events
-            sub_id = msg.parent_tool_use_id
+            sub_id = self._resolve_subagent_id(msg.parent_tool_use_id)
             if sub_id is not None:
                 events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
             else:
                 events.append(AgentEvent("stream", text))
             return events
 
         if isinstance(msg, AssistantMessage):
             # Subagent messages carry parent_tool_use_id → tag events so the UI groups
             # them under the sub-agent block instead of mixing with the parent's stream.
-            sub_id = getattr(msg, "parent_tool_use_id", None)
+            sub_id = self._resolve_subagent_id(
+                getattr(msg, "parent_tool_use_id", None)
+            )
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
                     events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
                     events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                 elif isinstance(block, ToolUseBlock):
                     try:
                         inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
@@ -334,57 +350,88 @@ class ClaudeBackend:
                 self._pending_model_error = str(err)
                 events.append(AgentEvent(
                     "error",
                     f"model error: {err}",
                     metadata={"model_error": str(err)},
                 ))
 
         elif isinstance(msg, UserMessage):
-            sub_id = getattr(msg, "parent_tool_use_id", None)
+            sub_id = self._resolve_subagent_id(
+                getattr(msg, "parent_tool_use_id", None)
+            )
             if hasattr(msg, 'content') and isinstance(msg.content, list):
                 for block in msg.content:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                         events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
         elif isinstance(msg, TaskStartedMessage):
             desc = getattr(msg, "description", "") or ""
             task_type = getattr(msg, "task_type", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
-            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}",
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id:
+                self._subagent_descriptions[task_id] = desc
+                self._subagent_types[task_id] = task_type
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            events.append(AgentEvent(
+                "subagent_start",
+                f"{desc} | type={task_type} | id={task_id} | "
+                f"tool_use_id={tool_use_id}",
                                      metadata={"subagent_id": task_id, "phase": "start",
                                                "description": desc, "task_type": task_type,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
-                                               "tool_use_id": getattr(msg, "tool_use_id", "") or ""}))
+                                               "tool_use_id": tool_use_id}))
 
         elif isinstance(msg, TaskProgressMessage):
             desc = getattr(msg, "description", "") or ""
             last_tool = getattr(msg, "last_tool_name", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id and desc:
+                self._subagent_descriptions[task_id] = desc
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            desc = desc or self._subagent_descriptions.get(task_id, "")
+            task_type = self._subagent_types.get(task_id, "")
             u = self._task_usage(getattr(msg, "usage", None))
             events.append(AgentEvent("subagent_progress",
-                                     f"{desc} | tool={last_tool} | tokens={u.get('total_tokens', 0)}",
+                                     f"{desc} | type={task_type} | id={task_id} | "
+                                     f"tool_use_id={tool_use_id} | tool={last_tool} | "
+                                     f"tokens={u.get('total_tokens', 0)}",
                                      metadata={"subagent_id": task_id, "phase": "progress",
-                                               "description": desc, "last_tool_name": last_tool,
+                                               "description": desc, "task_type": task_type,
+                                               "last_tool_name": last_tool,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "tool_use_id": tool_use_id,
                                                **u}))
 
         elif isinstance(msg, TaskNotificationMessage):
-            desc = getattr(msg, "description", "") or ""
             status = getattr(msg, "status", "") or ""
             summary = getattr(msg, "summary", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            desc = self._subagent_descriptions.get(task_id, "")
+            task_type = self._subagent_types.get(task_id, "")
             output_file = getattr(msg, "output_file", "") or ""
             u = self._task_usage(getattr(msg, "usage", None))
             data = getattr(msg, "data", None)
-            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}",
+            events.append(AgentEvent(
+                "subagent_end",
+                f"{desc} | type={task_type} | id={task_id} | "
+                f"tool_use_id={tool_use_id} | status={status} | {summary[:500]}",
                                      metadata={"subagent_id": task_id, "phase": "end",
-                                               "description": desc, "status": status,
+                                               "description": desc, "task_type": task_type,
+                                               "status": status,
                                                "summary": summary, "output_file": output_file,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "tool_use_id": tool_use_id,
                                                "raw_json": _json.dumps(data, ensure_ascii=False) if data else "",
                                                **u}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 99c6bdc5d..e53d40af4 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2171,23 +2171,32 @@ function _findLastBefore(parent, selector, anchor) {
         if (node.matches(selector)) return node;
         node = node.previousElementSibling;
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
 
-// Append a live sub-agent log line into its accordion body. If the accordion
-// isn't there yet (race: stream before start), no-op — the sub-agent block owns
-// its own rendering; live lines are best-effort decoration.
+// SDK stream events can beat TaskStarted by a few milliseconds. Buffer those
+// lines by parent tool id, then move them into the task-id card once it exists.
+const _pendingSubagentLogs = new Map();
 function appendSubagentLog(subId, evType, content) {
     const chat = $('#chat');
     const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
-    if (!host) return;
+    if (!host) {
+        if (!_pendingSubagentLogs.has(subId) && _pendingSubagentLogs.size >= 50) {
+            _pendingSubagentLogs.delete(_pendingSubagentLogs.keys().next().value);
+        }
+        const pending = _pendingSubagentLogs.get(subId) || [];
+        pending.push([evType, content]);
+        if (pending.length > 100) pending.shift();
+        _pendingSubagentLogs.set(subId, pending);
+        return;
+    }
     const body = host.querySelector('.sa-body');
     if (!body) return;
     if (evType === 'stream') {
         // Coalesce contiguous stream text into one line (typewriter feel)
         let last = body.lastElementChild;
         if (last && last.classList.contains('sa-stream')) {
             last.textContent += content;
         } else {
@@ -2202,16 +2211,26 @@ function appendSubagentLog(subId, evType, content) {
         line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
         const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
         line.textContent = `${icon} ${short}`;
         body.appendChild(line);
     }
     body.scrollTop = body.scrollHeight;
 }
 
+function _flushPendingSubagentLogs(sourceId, targetId) {
+    if (!sourceId || !targetId) return;
+    const pending = _pendingSubagentLogs.get(sourceId);
+    if (!pending) return;
+    _pendingSubagentLogs.delete(sourceId);
+    for (const [evType, content] of pending) {
+        appendSubagentLog(targetId, evType, content);
+    }
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 // payload = full SSE log object (carries subagent_id for sub-agent nesting)
 function addChatEntry(type, content, ts, anchor, payload) {
     if (HIDE_THINKING && type === 'thinking') return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
         appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
@@ -2394,24 +2413,27 @@ function addChatEntry(type, content, ts, anchor, payload) {
             if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
             else if (p) textParts.push(p);
         }
         const desc = textParts[0] || textParts[1] || '';
         const el = document.createElement('div');
         el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';
 
         const subId = (payload && payload.subagent_id) || meta.id || '';
+        const isBackground = meta.type === 'local_bash';
 
         if (type === 'subagent_start') {
             // Collapsible accordion: header + body where live sub-agent logs nest.
             el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
             if (subId) el.dataset.subagentId = subId;
+            el.dataset.subagentKind = isBackground ? 'background' : 'agent';
             const header = document.createElement('div');
             header.style.cssText = 'cursor:pointer;user-select:none';
-            header.innerHTML = `<span class="sa-caret">▶</span> 🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
+            const noun = isBackground ? 'Background task' : 'Sub-agent';
+            header.innerHTML = `<span class="sa-caret">▶</span> ${isBackground ? '⚙️' : '🤖'} <span style="color:#e2e8f0">${noun}: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
             const body = document.createElement('div');
             body.className = 'sa-body';
             body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
             let _expanded = false;
             header.addEventListener('click', () => {
                 _expanded = !_expanded;
                 body.style.display = _expanded ? 'block' : 'none';
                 header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
@@ -2430,47 +2452,53 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     prog.className = 'sa-progress';
                     prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                     host.appendChild(prog);
                 }
                 prog.textContent = line;
                 return;  // updated in place, no new bubble
             }
             el.style.cssText += ';color:#64748b';
-            el.textContent = `⏳ "${desc}" — ${line}`;
+            el.textContent = `⏳ ${isBackground ? 'Background task' : 'Sub-agent'} "${desc}" — ${line}`;
         } else {  // subagent_end → mark the accordion done + collapse
             const ok = !meta.status || meta.status === 'completed';
             const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
             const summaryText = textParts.slice(1).join(' | ').trim();
             if (host) {
                 const hdr = host.querySelector('div');
-                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
+                const noun = host.dataset.subagentKind === 'background' ? 'Background task' : 'Sub-agent';
+                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
                 const prog = host.querySelector('.sa-progress');
                 if (prog) prog.remove();
                 if (summaryText) {
                     const sumEl = document.createElement('div');
                     sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                     sumEl.textContent = summaryText;
                     host.appendChild(sumEl);
                 }
                 host.style.borderLeftColor = ok ? '#22c55e' : '#ef4444';
                 return;  // updated existing accordion, no new bubble
             }
             el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
-            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
+            const noun = isBackground ? 'Background task' : 'Sub-agent';
+            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
             if (summaryText) {
                 const sumEl = document.createElement('div');
                 sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
                 sumEl.textContent = summaryText.length > 300 ? summaryText.slice(0, 300) + '…' : summaryText;
                 el.appendChild(sumEl);
             }
         }
         addTimestamp(el, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(el);
+        if (type === 'subagent_start' && subId) {
+            _flushPendingSubagentLogs(subId, subId);
+            _flushPendingSubagentLogs(meta.tool_use_id, subId);
+        }
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     const div = document.createElement('div');
     div.className = `px-3 py-2 rounded-lg text-sm break-words ${
         type === 'user_message' ? 'chat-user ml-16' :
         type === 'tool' ? 'chat-tool' :
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index b2d03ee85..7b47c757d 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -248,17 +248,17 @@
             <!-- Agent Info -->
             <div id="agent-info" class="px-4 py-3 border-b border-slate-800/50 space-y-2">
                 <div class="flex items-center justify-between gap-2">
                     <span id="ai-name" class="font-semibold text-sm truncate min-w-0"></span>
                     <div class="flex items-center gap-2 shrink-0">
                         <button id="compact-btn" class="text-slate-500 hover:text-amber-300 text-xs hidden" title="Compact context">🗜</button>
                         <button id="restart-cli-btn" class="text-slate-500 hover:text-green-300 text-xs hidden" title="Restart CLI">♻️</button>
                         <button id="view-prompt-btn" class="text-slate-500 hover:text-indigo-300 text-xs hidden" title="View system prompt">📜</button>
-                        <button id="subagents-btn" class="text-slate-500 hover:text-purple-300 text-xs hidden" title="Sub-agents telemetry" onclick="openSubagentsModal()">🤖</button>
+                        <button id="subagents-btn" class="text-slate-500 hover:text-purple-300 text-xs hidden" title="Agent and background-task activity" onclick="openSubagentsModal()">🤖</button>
                         <span id="ai-status" class="text-xs font-mono"></span>
                     </div>
                 </div>
                 <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                     <span class="text-slate-500">Model</span><span id="ai-model" class="text-slate-300 break-all"></span>
                     <span class="text-slate-500">Role</span><span id="ai-role" class="text-purple-400 break-all"></span>
                     <span class="text-slate-500">Cost</span><span id="ai-cost" class="text-green-400"></span>
                     <span class="text-slate-500">Branch</span><span id="ai-branch" class="text-indigo-400 break-all font-mono"></span>
diff --git a/tests/test_backend_stream.py b/tests/test_backend_stream.py
index a54548c5f..10d657800 100644
--- a/tests/test_backend_stream.py
+++ b/tests/test_backend_stream.py
@@ -1,15 +1,20 @@
 """ClaudeBackend._convert StreamEvent scope filter + sub-agent tagging.
 
 Main-agent text_delta → "stream". Sub-agent text_delta (parent_tool_use_id set)
 → "subagent_stream" tagged with subagent_id (surfaced, not dropped). Non-text
 deltas (thinking/tool-arg/sig) and non-delta events are still dropped.
 """
-from claude_agent_sdk import StreamEvent
+from claude_agent_sdk import (
+    StreamEvent,
+    TaskNotificationMessage,
+    TaskProgressMessage,
+    TaskStartedMessage,
+)
 
 from app.backend_claude import ClaudeBackend
 from app.events import AgentEvent
 
 
 def _backend():
     return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")
 
@@ -77,16 +82,89 @@ def test_subagent_text_delta_becomes_subagent_stream():
     }, parent_tool_use_id="toolu_123")
     out = b._convert(msg)
     assert len(out) == 1
     assert out[0].type == "subagent_stream"
     assert out[0].content == "sub"
     assert out[0].metadata.get("subagent_id") == "toolu_123"
 
 
+def test_subagent_stream_resolves_parent_tool_use_to_task_id():
+    b = _backend()
+    start = TaskStartedMessage(
+        subtype="task_started",


## LATER FIX ce6e0eb70c (14.3 days later): fix: stabilize subagent lifecycle timestamps
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

fix: stabilize subagent lifecycle timestamps


diff --git a/app/db.py b/app/db.py
index 510a6c32f..1ce49b1f7 100644
--- a/app/db.py
+++ b/app/db.py
@@ -734,20 +734,26 @@ _SA_TEXT = ("sdk_session_id", "tool_use_id", "description", "task_type",
 _SA_NUM = ("total_tokens", "tool_uses", "duration_ms")
 
 
 def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
     """Insert or update one sub-agent row (keyed by session_id+task_id).
 
     start creates the row; progress/end update only the fields they carry.
     Empty text / zero numbers never overwrite an existing value.
+    Explicit starts keep the earliest known lifecycle timestamp.
     """
+    started_at = fields.get("started_at") or datetime.now(timezone.utc).isoformat()
     cols = ["session_id", "task_id", "started_at"]
-    vals = [session_id, task_id, datetime.now(timezone.utc).isoformat()]
-    updates = []
+    vals = [session_id, task_id, started_at]
+    updates = [
+        "started_at=CASE WHEN julianday(excluded.started_at) < "
+        "julianday(subagents.started_at) THEN excluded.started_at "
+        "ELSE subagents.started_at END"
+    ]
     for k in _SA_TEXT:
         if k in fields and fields[k] is not None:
             cols.append(k); vals.append(fields[k])
             updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
     for k in _SA_NUM:
         if k in fields and fields[k]:
             cols.append(k); vals.append(int(fields[k]))
             updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
diff --git a/app/session.py b/app/session.py
index 52aca72b3..b71549c97 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1024,27 +1024,31 @@ class AgentSession:
         self._log_futures.add(future)
         future.add_done_callback(self._log_futures.discard)
 
     def _persist_subagent(self, meta: dict, ended: bool = False) -> None:
         """Upsert sub-agent telemetry from a Task* event. Fire-and-forget.
 
         Only the fields the event carries are passed — subagent_upsert's
         NULLIF-COALESCE keeps prior values, so progress never wipes start's data.
+        Lifecycle timestamps are captured before the executor can reorder jobs.
         """
         task_id = meta.get("subagent_id")
         if not task_id:
             return
+        event_at = datetime.now(timezone.utc).isoformat()
         fields = {k: meta[k] for k in (
             "sdk_session_id", "tool_use_id", "description", "task_type", "status",
             "last_tool_name", "output_file", "summary", "raw_json",
             "total_tokens", "tool_uses", "duration_ms",
         ) if k in meta}
-        if ended:
-            fields["ended_at"] = datetime.now(timezone.utc).isoformat()
+        if meta.get("phase") == "start":
+            fields["started_at"] = event_at
+        if ended or meta.get("phase") == "end":
+            fields["ended_at"] = event_at
         from app.db import subagent_upsert
         asyncio.get_event_loop().run_in_executor(
             _db_executor(), lambda: subagent_upsert(self.id, task_id, **fields))
 
     def _to_db_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
             "model": self.model, "system_prompt": self.system_prompt,
diff --git a/tests/test_subagents.py b/tests/test_subagents.py
index 439b1a169..f15330851 100644
--- a/tests/test_subagents.py
+++ b/tests/test_subagents.py
@@ -76,16 +76,76 @@ def test_end_derives_duration_when_sdk_omits_usage(db):
     subagent_upsert("sess-1", "task-a", description="Background command",
                     task_type="local_bash")
     ended_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
     subagent_upsert("sess-1", "task-a", status="completed", ended_at=ended_at)
     sa = get_subagent("sess-1", "task-a")
     assert 1_500 <= sa["duration_ms"] <= 2_500
 
 
+def test_end_before_start_preserves_lifecycle_order(db):
+    from app.db import subagent_upsert, get_subagent
+    from app.routes.subagent import _duration_ms
+
+    started_at = "2026-07-17T00:00:00+00:00"
+    ended_at = "2026-07-17T00:00:02+00:00"
+    subagent_upsert("sess-1", "task-a", status="completed", summary="Done",
+                    ended_at=ended_at)
+    subagent_upsert("sess-1", "task-a", description="Explore X",
+                    task_type="Explore", started_at=started_at)
+
+    sa = get_subagent("sess-1", "task-a")
+    assert sa["description"] == "Explore X"
+    assert sa["task_type"] == "Explore"
+    assert sa["status"] == "completed"
+    assert datetime.fromisoformat(sa["started_at"]) <= datetime.fromisoformat(sa["ended_at"])
+    assert _duration_ms(sa) == 2_000
+
+
+def test_persist_subagent_start_captures_timestamp_before_executor(monkeypatch):
+    from app.session import AgentSession
+
+    captured = {}
+    event_at = datetime(2026, 7, 17, tzinfo=timezone.utc)
+
+    class FakeLoop:
+        def run_in_executor(self, executor, job):
+            captured["job"] = job
+
+    class FakeDateTime(datetime):
+        current = event_at
+
+        @classmethod
+        def now(cls, tz=None):
+            return cls.current
+
+    monkeypatch.setattr("app.session.asyncio.get_event_loop", lambda: FakeLoop())
+    monkeypatch.setattr("app.session._db_executor", lambda: object())
+    monkeypatch.setattr("app.session.datetime", FakeDateTime)
+
+    def fake_upsert(session_id, task_id, **fields):
+        captured["call"] = (session_id, task_id, fields)
+
+    monkeypatch.setattr("app.db.subagent_upsert", fake_upsert)
+    session = AgentSession(id="sess-1", name="worker", scope="/s", cwd="/c")
+
+    session._persist_subagent({
+        "subagent_id": "task-a", "phase": "start",
+        "description": "Explore X",
+    })
+    FakeDateTime.current = event_at + timedelta(seconds=5)
+    captured["job"]()
+
+    session_id, task_id, fields = captured["call"]
+    assert (session_id, task_id) == ("sess-1", "task-a")
+    assert fields["description"] == "Explore X"
+    assert fields["started_at"] == event_at.isoformat()
+    assert "ended_at" not in fields
+
+
 def test_two_subagents_same_session_distinct(db):
     from app.db import subagent_upsert, get_subagents
     subagent_upsert("sess-1", "task-a", description="A")
     subagent_upsert("sess-1", "task-b", description="B")
     rows = get_subagents("sess-1")
     assert {r["task_id"] for r in rows} == {"task-a", "task-b"}
 
 