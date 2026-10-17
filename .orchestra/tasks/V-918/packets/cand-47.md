# Candidate cand-47

## ORIGIN commit bc0d3c343f (2026-06-15): fix: missing modules in orchestrator, duplicate colors, clipboard on HTTP
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/manager.py b/app/manager.py
index 2aaaa4058..bb70eb297 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1084,17 +1084,21 @@ class SessionManager:
             if s.name == name and (scope is None or s.scope == scope):
                 return s.id
         for row in get_all_sessions(scope):
             if row["name"] == name:
                 return row["id"]
         return None
 
     def _pick_color(self) -> str:
-        used = [s.color for s in self.sessions.values()]
+        # Check both in-memory sessions AND DB to avoid duplicates on concurrent spawn / resume
+        used = {s.color for s in self.sessions.values() if s.color}
+        for row in get_all_sessions():
+            if row.get("color"):
+                used.add(row["color"])
         for c in COLOR_PALETTE:
             if c not in used:
                 return c
         from collections import Counter
         counts = Counter(used)
         return min(COLOR_PALETTE, key=lambda c: counts.get(c, 0))
 
     def stats(self, scope: str | None = None) -> dict:
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 9ab5c06d1..5e46c9207 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1737,17 +1737,26 @@ function addTimestamp(el, ts) {
 function addCopyBtn(el, text) {
     if (!el || el.querySelector('.copy-btn')) return;
     el.style.position = 'relative';
     const btn = document.createElement('button');
     btn.className = 'copy-btn';
     btn.textContent = '📋';
     btn.addEventListener('click', (e) => {
         e.stopPropagation();
-        navigator.clipboard.writeText(text);
+        // navigator.clipboard requires HTTPS — fallback for HTTP
+        if (navigator.clipboard && window.isSecureContext) {
+            navigator.clipboard.writeText(text);
+        } else {
+            const ta = document.createElement('textarea');
+            ta.value = text; ta.style.cssText = 'position:fixed;left:-9999px';
+            document.body.appendChild(ta); ta.select();
+            document.execCommand('copy');
+            document.body.removeChild(ta);
+        }
         btn.textContent = '✅';
         setTimeout(() => btn.textContent = '📋', 1500);
     });
     el.appendChild(btn);
 }
 
 let streamBubble = null;
 let streamContent = '';
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 5e9985af9..004e83a0c 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -16,30 +16,30 @@ defaults:
   docs_scaffold: false
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
     model: opus
     skills: [html-artifacts, vps-deploy, codex-debate]
-    modules: [git-workflow, orchestration]
+    modules: [git-workflow, orchestration, background-jobs, task-management]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     when: Managing a team of workers, decomposing tasks, approving plans
     not_for: Direct implementation — delegate to workers
     description: >
       Manages worker agents. Decomposes tasks, spawns workers, reviews results.
       Available worker roles are injected automatically from roles/ directory.
   sub-orchestrator:
     kind: orchestrator
     label: Sub-Orchestrator
     order: 1
     model: opus
-    modules: [git-workflow, orchestration]
+    modules: [git-workflow, orchestration, background-jobs, task-management]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "🎯"}
     when: Managing a sub-team within a larger hierarchy (department lead, tech lead, team lead)
     not_for: Direct implementation — delegate to workers
     description: >
       Manages a subset of workers under a parent orchestrator.
       Reports up to parent, delegates down to workers.


## LATER FIX 61b9918075 (89.9 days later): V-567: scope agent colors and repair live sessions
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

V-567: scope agent colors and repair live sessions

Orchestra-Operation: 37adf47d-2d4f-4efd-a884-ab9806cc7f38


diff --git a/app/manager.py b/app/manager.py
index 5a72b4cb6..f88396b82 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -178,16 +178,19 @@ def next_adhoc_branch(worker_name: str) -> str:
     """
     return f"adhoc-{int(time.time())}-{next(_adhoc_serial)}/{worker_name}"
 
 from app.runtime_env import MCP_BASE_ENV, MCP_STDIO_CMD  # noqa: F401 — re-exported for callers
 
 COLOR_PALETTE = [
     "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
     "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
+    "#60a5fa", "#c084fc", "#facc15", "#22d3ee", "#fb923c",
+    "#f87171", "#a3e635", "#e879f9", "#67e8f9", "#93c5fd",
+    "#86efac", "#fca5a5", "#fde68a", "#5eead4",
 ]
 
 
 async def _wait_owned_task(task: asyncio.Task) -> asyncio.CancelledError | None:
     """Wait without letting caller cancellation penetrate an owned operation."""
     cancellation = None
     current = asyncio.current_task()
     while not task.done():
@@ -749,17 +752,17 @@ class SessionManager:
         raw_effort = getattr(_rr_effort, "effort", None) if _rr_effort else None
         effort = resolve_effort(raw_effort, model, bt)
         session_id = str(uuid.uuid4())
         session = AgentSession(
             id=session_id, name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, prompt_overlay=prompt_overlay, role=role,
             parent_id=parent_id, parent_name=parent_name,
             pipeline=pipeline, profile=profile,
-            color="" if is_orch else self._pick_color(),
+            color="" if is_orch else self._pick_color(scope),
             mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name,
                                          extra=custom_mcp, session_id=session_id,
                                          pipeline=pipeline, disabled_tools=disabled_tools),
             disabled_tools=parse_disabled_tools(disabled_tools),
             mcp_servers_custom=custom_mcp,
             backend_type=bt, effort=effort, task_id=task_id, description=description,
             base_branch=base_branch,
             owned_dirs=owned_dirs,
@@ -2006,17 +2009,19 @@ class SessionManager:
             worktree_path=wt_path, branch=db_branch,
             base_branch=db_row.get("base_branch") or "",
             created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
             role=role,
             parent_id=db_row.get("parent_id", ""),
             parent_name=db_row.get("parent_name", ""),
             pipeline=pipeline,
             profile=db_row.get("profile", ""),
-            color="" if is_orch else (db_row.get("color") or self._pick_color()),
+            color="" if is_orch else (
+                db_row.get("color") or self._pick_color(db_row["scope"])
+            ),
             mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], role,
                                          parent_name=db_row.get("parent_name", ""),
                                          extra=custom_mcp, session_id=db_row["id"], pipeline=pipeline,
                                          disabled_tools=parse_disabled_tools(db_row.get("disabled_tools"))),
             disabled_tools=parse_disabled_tools(db_row.get("disabled_tools")),
             mcp_servers_custom=custom_mcp,
             backend_type=stored_bt, effort=db_row.get("effort") or None,
             runtime_handoff=db_row.get("runtime_handoff") or "",
@@ -2275,36 +2280,111 @@ class SessionManager:
 
     def get_session_id(self, name: str, scope: str) -> str | None:
         for s in self.sessions.values():
             if s.name == name and s.scope == scope:
                 return s.id
         db_row = get_session_by_name(name, scope)
         return db_row["id"] if db_row else None
 
-    def _pick_color(self) -> str:
-        # Check both in-memory sessions AND DB to avoid duplicates on concurrent spawn / resume
-        used = {s.color for s in self.sessions.values() if s.color}
-        for row in get_all_sessions():
-            if row.get("color"):
-                used.add(row["color"])
-        for c in COLOR_PALETTE:
-            if c not in used:
-                return c
+    def _pick_color(self, scope: str | None = None) -> str:
+        # Check both in-memory sessions AND DB to avoid duplicates on concurrent spawn / resume.
+        colors = self._live_worker_colors(scope)
+        used = set(colors)
+        for color in COLOR_PALETTE:
+            if color not in used:
+                return color
         from collections import Counter
-        counts = Counter(used)
-        return min(COLOR_PALETTE, key=lambda c: counts.get(c, 0))
+        counts = Counter(colors)
+        return min(COLOR_PALETTE, key=lambda color: (counts[color], COLOR_PALETTE.index(color)))
+
+    def _live_worker_colors(self, scope: str | None = None) -> list[str]:
+        """Return one color per live worker, optionally limited to one project."""
+        rows_by_id = {
+            row["id"]: row
+            for row in get_all_sessions()
+            if row.get("status") != "archived"
+            and not bool(row.get("is_orchestrator"))
+            and (scope is None or row.get("scope") == scope)
+        }
+        for session in self.sessions.values():
+            if session.is_orchestrator or (scope is not None and session.scope != scope):
+                continue
+            rows_by_id.setdefault(session.id, {"color": session.color})
+        return [row["color"] for row in rows_by_id.values() if row.get("color")]
+
+    def reconcile_live_colors(self) -> None:
+        """Reassign live worker colors evenly within each project and persist them."""
+        from collections import Counter, defaultdict
+        from app.db import _conn
+
+        rows_by_id = {
+            row["id"]: row
+            for row in get_all_sessions()
+            if row.get("status") != "archived"
+            and not bool(row.get("is_orchestrator"))
+        }
+        for session in self.sessions.values():
+            if session.is_orchestrator:
+                continue
+            rows_by_id.setdefault(session.id, {
+                "id": session.id,
+                "scope": session.scope,
+                "created_at": session.created_at.isoformat(),
+                "color": session.color,
+            })
+
+        by_scope = defaultdict(list)
+        for row in rows_by_id.values():
+            by_scope[row.get("scope") or ""].append(row)
+        assignments = {}
+        for scope_rows in by_scope.values():
+            counts = Counter()
+            for row in sorted(scope_rows, key=lambda item: (
+                item.get("created_at") or "", item["id"],
+            )):
+                color = min(
+                    COLOR_PALETTE,
+                    key=lambda candidate: (counts[candidate], COLOR_PALETTE.index(candidate)),
+                )
+                assignments[row["id"]] = color
+                counts[color] += 1
+
+        with _conn() as connection:
+            if assignments:
+                connection.executemany(
+                    "UPDATE sessions SET color=? WHERE id=? AND status != 'archived' "
+                    "AND is_orchestrator=0",
+                    [(color, session_id) for session_id, color in assignments.items()],
+                )
+            connection.execute(
+                "UPDATE sessions SET color='' WHERE status != 'archived' "
+                "AND is_orchestrator=1",
+            )
+        for session in self.sessions.values():
+            if session.is_orchestrator:
+                session.color = ""
+                if session.db_row is not None:
+                    session.db_row["color"] = ""
+                continue
+            color = assignments.get(session.id)
+            if color is None:
+                continue
+            session.color = color
+            if session.db_row is not None:
+                session.db_row["color"] = color
 
     def stats(self, scope: str | None = None) -> dict:
         return get_stats(scope)
 
     # ── Startup / Shutdown ──
 
 
     async def auto_resume_all(self) -> None:
+        self.reconcile_live_colors()
         from app.db import _conn
         with _conn() as c:
             # 'interrupted' — graceful shutdown успел пометить оборванный ход;
             # 'running' — не успел (SIGKILL/OOM). Оба означают одно: ход прерван
             # рестартом. Читать только 'running' значило будить лишь тех, кого
             # застал аварийный путь (#160).
             was_running = {r["id"] for r in c.execute(
                 "SELECT id FROM sessions WHERE status IN ('running', 'interrupted')"
diff --git a/tests/test_agent_colors_567.py b/tests/test_agent_colors_567.py
new file mode 100644
index 000000000..235f11ce7
--- /dev/null
+++ b/tests/test_agent_colors_567.py
@@ -0,0 +1,85 @@
+"""Core color allocation and startup repair checks for V-567."""
+
+from collections import Counter
+
+import pytest
+
+from app.db import archive_session, get_all_sessions, get_session, save_session
+from app.manager import COLOR_PALETTE, SessionManager
+
+
+@pytest.fixture
+def db(tmp_path, monkeypatch):
+    db_path = tmp_path / "colors.db"
+    monkeypatch.setattr("app.db.DB_PATH", db_path)
+    from app.db import init_db
+    init_db()
+    return db_path
+
+
+def _session(session_id, *, scope="/project", color="", is_orchestrator=False):
+    save_session({
+        "id": session_id,
+        "name": session_id,
+        "scope": scope,
+        "cwd": scope,
+        "model": "claude-sonnet-5[1m]",
+        "system_prompt": "",
+        "status": "idle",
+        "session_id": None,
+        "cost_usd": 0.0,
+        "worktree_path": None,
+        "branch": None,
+        "base_branch": "",
+        "needs_switch": 0,
+        "is_orchestrator": is_orchestrator,
+        "color": color,
+        "created_at": "2026-09-01T00:00:00+00:00",
+        "finished_at": None,
+    })
+
+
+def test_fallback_counts_each_live_color_occurrence(db):
+    """The first palette color is not selected merely because it sorts first."""
+    for index, color in enumerate(COLOR_PALETTE):
+        _session(f"w{index}", color=color)
+    _session("w99", color=COLOR_PALETTE[0])
+
+    assert SessionManager()._pick_color("/project") == COLOR_PALETTE[1]
+
+
+def test_allocator_is_scoped_and_archived_rows_do_not_occupy_colors(db):
+    for index, color in enumerate(COLOR_PALETTE):
+        _session(f"a{index}", scope="/a", color=color)
+    archived_id = "archived"
+    _session(archived_id, scope="/b", color=COLOR_PALETTE[0])
+    archive_session(archived_id)
+
+    manager = SessionManager()
+    assert manager._pick_color("/b") == COLOR_PALETTE[0]
+    assert manager._pick_color("/a") == COLOR_PALETTE[0]
+
+
+def test_startup_recolors_live_workers_per_scope_and_preserves_archived(db):
+    for index in range(len(COLOR_PALETTE) + 3):
+        _session(f"a{index}", scope="/a", color=COLOR_PALETTE[0])
+    _session("b0", scope="/b", color=COLOR_PALETTE[0])
+    _session("b1", scope="/b", color=COLOR_PALETTE[0])
+    _session("old", scope="/a", color="#123456")
+    archive_session("old")
+    _session("orch", scope="/a", color="#123456", is_orchestrator=True)
+
+    manager = SessionManager()
+    manager.reconcile_live_colors()
+    first = {row["id"]: row["color"] for row in get_all_sessions(include_archived=True)}
+    manager.reconcile_live_colors()
+    second = {row["id"]: row["color"] for row in get_all_sessions(include_archived=True)}
+
+    live_a = [color for sid, color in first.items() if sid.startswith("a")]
+    live_b = [color for sid, color in first.items() if sid.startswith("b")]
+    assert max(Counter(live_a).values()) - min(Counter(live_a).values()) <= 1
+    assert len(set(live_b)) == 2
+    assert first["old"] == second["old"] == "#123456"
+    assert first["orch"] == second["orch"] == ""
+    assert first == second
+    assert get_session("old")["status"] == "archived"