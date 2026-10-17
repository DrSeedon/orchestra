# Candidate cand-00

## ORIGIN commit 0bb118cac7 (2026-06-01): #29: scope-change: research + implementation plan for changing orchestrator scope/repo_path
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/db.py b/app/db.py
index 7f6416a78..dfb8ee986 100644
--- a/app/db.py
+++ b/app/db.py
@@ -446,16 +446,64 @@ def save_session(s: dict) -> None:
                 role=excluded.role,
                 parent_id=excluded.parent_id,
                 parent_name=excluded.parent_name,
                 mcp_servers_custom=excluded.mcp_servers_custom,
                 owned_dirs=excluded.owned_dirs
         """, s)
 
 
+def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
+    """Move an orchestrator's session to a new scope in one transaction.
+
+    Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
+    bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
+    session_id (Claude resume token) is left intact — context survives.
+
+    Rejected if another session with the same name already lives in new_scope
+    (UNIQUE(name, scope)). tm_projects/test_lock migration is skipped on UNIQUE
+    collision (target already taken) but the session move still succeeds.
+    """
+    with _conn() as c:
+        row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
+        if not row:
+            return {"error": f"session not found: {session_id}"}
+        name = row["name"]
+        clash = c.execute(
+            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
+            (name, new_scope, session_id),
+        ).fetchone()
+        if clash:
+            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}
+
+        cur = c.execute(
+            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
+            (new_scope, new_cwd, session_id, old_scope),
+        )
+        if cur.rowcount == 0:
+            return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}
+
+        tm_migrated = False
+        target_taken = c.execute("SELECT 1 FROM tm_projects WHERE scope=?", (new_scope,)).fetchone()
+        if not target_taken:
+            cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
+            tm_migrated = cur.rowcount > 0
+
+        c.execute(
+            "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
+            (new_scope, old_scope),
+        )
+
+        lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
+        if not lock_target_taken:
+            c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))
+
+        return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}
+
+
 def get_session(session_id: str) -> dict | None:
     with _conn() as c:
         row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
         return dict(row) if row else None
 
 
 def get_session_by_name(name: str, scope: str) -> dict | None:
     with _conn() as c:
diff --git a/app/main.py b/app/main.py
index 95e021f81..119845e32 100644
--- a/app/main.py
+++ b/app/main.py
@@ -145,16 +145,22 @@ class ScopeRequest(BaseModel):
 
 
 class TestLockRequest(BaseModel):
     scope: str
     holder: str
     reason: str = ""
 
 
+class ChangeScopeRequest(BaseModel):
+    old_scope: str
+    new_scope: str
+    new_cwd: Optional[str] = None
+
+
 @app.get("/", response_class=HTMLResponse)
 async def dashboard(request: Request):
     return templates.TemplateResponse(request, "dashboard.html")
 
 
 @app.get("/login", response_class=HTMLResponse)
 async def login_page(request: Request):
     if not is_auth_enabled():
@@ -257,17 +263,22 @@ _DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".s
 
 
 def _is_safe_path(path: str) -> bool:
     try:
         p = Path(path).resolve()
         resolved = str(p)
     except (ValueError, OSError):
         return False
-    if not any(resolved.startswith(root) for root in _get_allowed_roots()):
+    def _within(root: str) -> bool:
+        try:
+            return os.path.commonpath([os.path.realpath(root), resolved]) == os.path.realpath(root)
+        except (ValueError, OSError):
+            return False
+    if not any(_within(root) for root in _get_allowed_roots()):
         return False
     home = str(Path.home())
     for part in p.parts:
         if part in _DENIED_PARTS or part.startswith(".env"):
             return False
     if resolved.startswith(home):
         for part in _DENIED_HOME_PARTS:
             if f"{home}/{part}" in resolved:
@@ -1072,16 +1083,29 @@ async def list_orchestrators():
 
 
 @app.delete("/api/orchestrators/{name}")
 async def delete_orchestrator(name: str, scope: str, delete_tg_topics: bool = False):
     result = await manager.remove_scope(scope, delete_tg_topics=delete_tg_topics)
     return {"ok": True, **result}
 
 
+@app.post("/api/orchestrators/{name}/change-scope")
+async def change_orchestrator_scope_endpoint(name: str, req: ChangeScopeRequest):
+    new_scope = req.new_scope.rstrip("/")
+    new_cwd = (req.new_cwd or req.new_scope).rstrip("/")
+    if not _is_safe_path(new_scope) or not _is_safe_path(new_cwd):
+        return JSONResponse({"error": "path not in allowed roots"}, status_code=403)
+    result = await manager.change_orchestrator_scope(
+        name, req.old_scope.rstrip("/"), new_scope, new_cwd)
+    if result.get("error"):
+        return JSONResponse(result, status_code=409)
+    return result
+
+
 @app.get("/api/test-lock")
 async def test_lock_status_endpoint(scope: str):
     from app.db import get_test_lock
     row = get_test_lock(scope)
     if not row:
         return {"held": False, "holder": None, "reason": None, "acquired_at": None}
     return {"held": True, "holder": row["holder"],
             "reason": row["reason"], "acquired_at": row["acquired_at"]}
diff --git a/app/manager.py b/app/manager.py
index 12a3f68e2..67f262d3b 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -537,16 +537,98 @@ class SessionManager:
             await session._disconnect_backend()
             if session.worktree_path:
                 try:
                     await asyncio.to_thread(remove_worktree, session.scope, session.worktree_path)
                 except Exception:
                     pass
         delete_session(session_id)
 
+    async def change_orchestrator_scope(self, name: str, old_scope: str,
+                                         new_scope: str, new_cwd: str) -> dict:
+        """Move an idle, worker-free orchestrator to a new scope/cwd.
+
+        Updates DB (db.change_scope), then rebuilds the runtime: kills the old MCP
+        subprocess via _disconnect_backend(), swaps scope/cwd/mcp_servers, and lets
+        the backend lazily reconnect on the next send() with the new ORCHESTRA_SCOPE.
+        session_id is preserved → context survives.
+        """
+        old_scope = old_scope.rstrip("/")
+        new_scope = new_scope.rstrip("/")
+        new_cwd = new_cwd.rstrip("/")
+        session = self.get_by_name(name, old_scope)
+        if not isinstance(session, AgentSession):
+            return {"error": f"orchestrator '{name}' not loaded in scope '{old_scope}'"}
+        if not session.is_orchestrator:
+            return {"error": f"'{name}' is not an orchestrator — scope change is orchestrator-only"}
+        if not Path(new_cwd).is_dir():
+            return {"error": f"new_cwd does not exist: {new_cwd}"}
+
+        live_workers = self._live_workers_in_scope(old_scope)
+        if live_workers:
+            return {"error": f"cannot change scope: live workers in '{old_scope}' — "
+                             f"merge+kill first: {', '.join(live_workers)}"}
+
+        # Hold the session lifecycle lock so a concurrent send() cannot flip
+        # the session IDLE→RUNNING between the idle check and the disconnect.
+        # (send() only starts a fresh turn inside this same lock.)
+        async with session._lifecycle_lock:
+            if session.status.value == "running":
+                return {"error": "cannot change scope while running — wait for idle"}
+
+            # Re-check under the lock right before the DB write to shrink the
+            # worker-spawn TOCTOU window (a spawn could have landed since the
+            # pre-lock scan). Full closure needs a scope-level spawn lock.
+            live_workers = self._live_workers_in_scope(old_scope)
+            if live_workers:
+                return {"error": f"cannot change scope: live workers appeared in '{old_scope}' — "
+                                 f"merge+kill first: {', '.join(live_workers)}"}
+
+            # Stop the backend (no new persists from this session) and drain any
+            # in-flight _persist() BEFORE the transaction, so change_scope()'s
+            # synchronous scope+cwd write is the last writer. Otherwise a stale
+            # queued persist (snapshot cwd=/old) could land after the transaction
+            # and clobber cwd, leaving scope=/new + cwd=/old on disk.
+            await session._disconnect_backend()
+            await session._drain_persist()
+
+            from app.db import change_scope
+            result = change_scope(session.id, old_scope, new_scope, new_cwd)
+            if not result.get("ok"):
+                return result
+
+            session.scope = new_scope
+            session.cwd = new_cwd
+            session.mcp_servers = _make_mcp_config(name, new_scope, session.role,
+                                                   extra=session.mcp_servers_custom)
+            # No session._persist() here: change_scope() already wrote scope+cwd
+            # synchronously in its transaction (the last writer after the drain).
+        logger.info(f"Orchestrator '{name}' scope changed: {old_scope} → {new_scope}")
+        return result
+
+    def _live_workers_in_scope(self, scope: str) -> list[str]:
+        """Names of active (idle/running/waiting) workers in scope, from both the
+        in-memory registry and the DB (catches unloaded-but-active worker rows).
+        Deduplicated by session id."""
+        active = ("idle", "running", "waiting")
+        seen_ids: set[str] = set()
+        names: set[str] = set()
+        for s in self.sessions.values():
+            if s.scope == scope and not s.is_orchestrator and s.status.value in active:
+                seen_ids.add(s.id)
+                names.add(s.name)
+        for row in get_all_sessions(scope):
+            if row["id"] in seen_ids:
+                continue
+            if is_orchestrator_role(row.get("role", "worker")):
+                continue
+            if (row.get("status") or "") in active:
+                names.add(row["name"])
+        return sorted(names)
+
     async def remove_scope(self, scope: str, delete_tg_topics: bool = False) -> dict:
         orch_names: list[str] = []
         for s in self.sessions.values():
             if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
                 orch_names.append(s.name)
         for row in get_all_sessions(scope):
             if is_orchestrator_role(row.get("role", "worker")) and row["name"] not in orch_names:
                 orch_names.append(row["name"])
diff --git a/app/session.py b/app/session.py
index 5bf512a62..b81c38ff9 100644
--- a/app/session.py
+++ b/app/session.py
@@ -106,16 +106,17 @@ class AgentSession:
     _pending_messages: list = field(default_factory=list, repr=False)
     on_idle: Optional[callable] = field(default=None, repr=False)
     _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _hibernated: bool = field(default=False, repr=False)
     _compacting: bool = field(default=False, repr=False)
     _last_cost: float = field(default=0.0, repr=False)
     _last_cost_cached: float = field(default=0.0, repr=False)
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
+    _persist_futs: set = field(default_factory=set, repr=False)
     _turn_gen: int = field(default=0, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
 
     TURN_TIMEOUT = 600
 
     @property
     def is_orchestrator(self) -> bool:
@@ -738,17 +739,24 @@ class AgentSession:
     async def stop(self) -> None:
         self._cancel_auto_report()
         await self._disconnect_backend()
         self._hibernated = False
         self.status = AgentStatus.IDLE
         self._persist()
 
     def _persist(self) -> None:
-        asyncio.get_event_loop().run_in_executor(None, save_session, self._to_db_dict())
+        fut = asyncio.get_event_loop().run_in_executor(None, save_session, self._to_db_dict())
+        self._persist_futs.add(fut)
+        fut.add_done_callback(self._persist_futs.discard)
+
+    async def _drain_persist(self) -> None:
+        pending = [f for f in self._persist_futs if not f.done()]
+        if pending:
+            await asyncio.gather(*pending, return_exceptions=True)
 
     def _log(self, type: str, content: str) -> None:
         asyncio.get_event_loop().run_in_executor(None, add_log, self.id, datetime.now(timezone.utc), type, content)
 
     def _to_db_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
             "model": self.model, "system_prompt": self.system_prompt,
diff --git a/app/static/js/app.js b/app/static/js/app.js
index b99ed89ef..dd56eb6be 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -792,16 +792,19 @@ function initTabContextMenu() {
             item.addEventListener('mouseleave', () => item.style.background = '');
             item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
             return item;
         };
         menu.appendChild(mkItem('👁 Скрыть', '#94a3b8', () => {
             const h = _getHiddenTabs(); h.add(name); _setHiddenTabs(h);
             renderOrchTabs(orchData);
         }));
+        menu.appendChild(mkItem('📁 Сменить папку', '#60a5fa', () => {
+            changeOrchScope(name, scope);
+        }));
         menu.appendChild(mkItem('🗑 Удалить', '#ef4444', () => {
             openDeleteOrchModal(name, scope);
         }));
         document.body.appendChild(menu);
         const rect = menu.getBoundingClientRect();
         if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
         if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
     });
@@ -837,16 +840,33 @@ function openDeleteOrchModal(name, scope) {
             alert(`Delete failed: ${e.message}`);
         }
     };
     $('#delete-orch-cancel').onclick = close;
     $('#delete-orch-modal-close').onclick = close;
     modal.onclick = (e) => { if (e.target === modal) close(); };
 }
 
+async function changeOrchScope(name, oldScope) {
+    const newScope = prompt(`Новая папка для "${name}" (контекст сессии сохранится):`, oldScope);
+    if (!newScope || newScope.trim() === oldScope) return;
+    const ns = newScope.trim().replace(/\/+$/, '');
+    try {
+        const res = await api(`/api/orchestrators/${name}/change-scope`, {
+            method: 'POST',
+            headers: { 'Content-Type': 'application/json' },
+            body: JSON.stringify({ old_scope: oldScope, new_scope: ns }),
+        });
+        await loadOrchestrators();
+        selectOrchestrator(name, res.scope || ns);
+    } catch (e) {
+        alert(`Смена папки не удалась: ${e.message}`);
+    }
+}
+
 function _updateHiddenBtn() {
     const btn = $('#hidden-tabs-btn');
     if (!btn) return;
     const hidden = _getHiddenTabs();
     const hasHidden = [...hidden].some(n => orchData.find(o => o.name === n));
     btn.classList.toggle('hidden', !hasHidden);
     if (hasHidden) btn.textContent = `👁 ${[...hidden].filter(n => orchData.find(o => o.name === n)).length}`;
 }
diff --git a/tests/test_api.py b/tests/test_api.py
index ce64502bf..685f9fd07 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -234,8 +234,65 @@ async def test_merge_endpoint_passes_target(monkeypatch):
         scope = "/s"
         id = "sid"
         name = "w"
     monkeypatch.setattr(mainmod.manager, "get_by_name", lambda name, scope: FakeSession())
 
     import asyncio
     res = await mainmod.merge_session("w", {"scope": "/s", "target": "feature/auth"})
     assert captured["target_branch"] == "feature/auth"
+
+
+class TestChangeScopeEndpoint:
+    def test_success(self, client, tmp_path):
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        from app.main import manager
+        with patch.object(manager, "change_orchestrator_scope",
+                          new=AsyncMock(return_value={"ok": True, "scope": str(newdir), "cwd": str(newdir)})) as m:
+            r = client.post("/api/orchestrators/orch/change-scope", json={
+                "old_scope": "/tmp", "new_scope": str(newdir),
+            })
+        assert r.status_code == 200
+        assert r.json()["ok"] is True
+        # new_cwd defaults to new_scope
+        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(newdir))
+
+    def test_explicit_cwd(self, client, tmp_path):
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        cwddir = tmp_path / "cwddir"; cwddir.mkdir()
+        from app.main import manager
+        with patch.object(manager, "change_orchestrator_scope",
+                          new=AsyncMock(return_value={"ok": True})) as m:
+            client.post("/api/orchestrators/orch/change-scope", json={
+                "old_scope": "/tmp", "new_scope": str(newdir), "new_cwd": str(cwddir),
+            })
+        m.assert_awaited_once_with("orch", "/tmp", str(newdir), str(cwddir))
+
+    def test_403_unsafe_path(self, client):
+        r = client.post("/api/orchestrators/orch/change-scope", json={
+            "old_scope": "/tmp", "new_scope": "/etc/passwd",
+        })
+        assert r.status_code == 403
+
+    def test_409_on_manager_error(self, client, tmp_path):
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        from app.main import manager
+        with patch.object(manager, "change_orchestrator_scope",
+                          new=AsyncMock(return_value={"error": "live workers in scope"})):
+            r = client.post("/api/orchestrators/orch/change-scope", json={
+                "old_scope": "/tmp", "new_scope": str(newdir),
+            })
+        assert r.status_code == 409
+        assert "error" in r.json()
+
+    def test_422_missing_fields(self, client):
+        r = client.post("/api/orchestrators/orch/change-scope", json={"old_scope": "/tmp"})
+        assert r.status_code == 422
+
+    def test_403_sibling_prefix_escape(self, client, tmp_path):
+        # /tmp_evil must NOT pass just because it shares the "/tmp" prefix
+        from app.main import manager
+        with patch.object(manager, "change_orchestrator_scope", new=AsyncMock()) as m:
+            r = client.post("/api/orchestrators/orch/change-scope", json={
+                "old_scope": "/tmp", "new_scope": "/tmproot_escape",
+            })
+        assert r.status_code == 403
+        m.assert_not_awaited()
diff --git a/tests/test_db.py b/tests/test_db.py
index e726c6eb7..db7f83a2e 100644
--- a/tests/test_db.py
+++ b/tests/test_db.py
@@ -506,8 +506,116 @@ class TestBgMigration:
             "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
         })
         assert any(j["type"] == "cron" for j in bg_get_active_all())
 
     def test_migrate_idempotent_on_fresh_db(self, db):
         # Fresh DB already has no type CHECK; init_db again must not error.
         from app.db import init_db
         init_db()
+
+
+class TestChangeScope:
+    def _orch(self, scope="/old/proj", name="orch", sid="orch-uuid-1"):
+        return {
+            "id": sid, "name": name, "scope": scope, "cwd": scope,
+            "model": "claude-opus-4-8", "system_prompt": "orch",
+            "status": "idle", "session_id": "sdk-abc", "cost_usd": 0.0,
+            "worktree_path": None, "branch": None, "is_orchestrator": True,
+            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
+            "finished_at": None, "role": "orchestrator",
+        }
+
+    def test_updates_scope_and_cwd(self, db):
+        from app.db import save_session, get_session, change_scope
+        save_session(self._orch())
+        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        assert res["ok"] is True
+        got = get_session("orch-uuid-1")
+        assert got["scope"] == "/new/proj"
+        assert got["cwd"] == "/new/proj"
+
+    def test_session_id_preserved(self, db):
+        from app.db import save_session, get_session, change_scope
+        save_session(self._orch())
+        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        got = get_session("orch-uuid-1")
+        assert got["session_id"] == "sdk-abc"  # context resume token intact
+
+    def test_name_collision_in_target_scope_rejected(self, db):
+        from app.db import save_session, get_session, change_scope
+        save_session(self._orch(scope="/old/proj", name="orch", sid="A"))
+        # another agent with same name already lives in target scope
+        save_session(self._orch(scope="/new/proj", name="orch", sid="B"))
+        res = change_scope("A", "/old/proj", "/new/proj", "/new/proj")
+        assert res.get("ok") is not True
+        assert "error" in res
+        # original untouched (rolled back)
+        assert get_session("A")["scope"] == "/old/proj"
+
+    def test_migrates_tm_project_scope(self, db):
+        from app.db import save_session, change_scope, _conn
+        from app.tm import ensure_project
+        save_session(self._orch())
+        with _conn() as c:
+            ensure_project(c, "proj1", scope="/old/proj", prefix="OLD")
+            c.commit()
+        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        with _conn() as c:
+            row = c.execute("SELECT scope FROM tm_projects WHERE id='proj1'").fetchone()
+        assert row["scope"] == "/new/proj"
+
+    def test_tm_project_collision_keeps_session_change(self, db):
+        from app.db import save_session, change_scope, get_session, _conn
+        from app.tm import ensure_project
+        save_session(self._orch())
+        with _conn() as c:
+            ensure_project(c, "p_old", scope="/old/proj", prefix="OLD")
+            ensure_project(c, "p_new", scope="/new/proj", prefix="NEW")
+            c.commit()
+        # tm_projects.scope is UNIQUE — target taken. Session scope must still change.
+        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        assert res["ok"] is True
+        assert get_session("orch-uuid-1")["scope"] == "/new/proj"
+        with _conn() as c:
+            old = c.execute("SELECT scope FROM tm_projects WHERE id='p_old'").fetchone()
+        assert old["scope"] == "/old/proj"  # not migrated (collision)
+        assert res.get("tm_project_migrated") is False
+
+    def test_migrates_active_bg_jobs(self, db):
+        from app.db import save_session, change_scope, bg_save_job, _conn
+        save_session(self._orch())
+        now = datetime.now(timezone.utc)
+        common = {
+            "config": "{}", "message": "", "target_session_id": "orch-uuid-1",
+            "target_name": "orch", "target_scope": "/old/proj", "created_by_name": "",
+            "expires_at": (now + timedelta(hours=1)).isoformat(),
+            "trigger_at": None, "created_at": now.isoformat(), "last_output": "",
+        }
+        bg_save_job({**common, "id": "j-active", "type": "timer", "status": "active"})
+        bg_save_job({**common, "id": "j-done", "type": "timer", "status": "triggered"})
+        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        with _conn() as c:
+            a = c.execute("SELECT target_scope FROM bg_jobs WHERE id='j-active'").fetchone()
+            d = c.execute("SELECT target_scope FROM bg_jobs WHERE id='j-done'").fetchone()
+        assert a["target_scope"] == "/new/proj"
+        assert d["target_scope"] == "/old/proj"  # terminal job not migrated
+
+    def test_migrates_test_lock(self, db):
+        from app.db import save_session, change_scope, acquire_test_lock, get_test_lock
+        save_session(self._orch())
+        acquire_test_lock("/old/proj", "orch", "running suite")
+        change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        assert get_test_lock("/old/proj") is None
+        moved = get_test_lock("/new/proj")
+        assert moved is not None and moved["holder"] == "orch"
+
+    def test_stale_old_scope_rejected(self, db):
+        # session already moved to /new/proj; a retried request with stale
+        # old_scope=/old/proj must NOT partially migrate related tables.
+        from app.db import save_session, change_scope, get_session, acquire_test_lock, get_test_lock
+        save_session(self._orch(scope="/new/proj"))  # already in target
+        acquire_test_lock("/new/proj", "orch", "x")
+        res = change_scope("orch-uuid-1", "/old/proj", "/new/proj", "/new/proj")
+        assert res.get("ok") is not True
+        assert "error" in res
+        assert get_session("orch-uuid-1")["scope"] == "/new/proj"  # untouched
+        assert get_test_lock("/new/proj") is not None  # lock not orphaned
diff --git a/tests/test_manager.py b/tests/test_manager.py
index eb6acebde..1517a6a42 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -492,8 +492,186 @@ class TestSystemPromptAppend:
         from tests.conftest import make_backend_mock
         with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
             with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
                 session = await mgr.create_session(
                     name="w-sp3", scope="/s", cwd="/tmp", model="m",
                     role="orchestrator",
                 )
         assert session.system_prompt == "ROLE_BASE"
+
+
+class TestChangeOrchestratorScope:
+    async def _make_orch(self, mgr, name="orch", scope="/old/proj"):
+        from tests.conftest import make_backend_mock
+        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+            s = await mgr.create_session(
+                name=name, scope=scope, cwd="/tmp", model="claude-opus-4-8",
+                is_orchestrator=True,
+            )
+        s.session_id = "sdk-resume-token"
+        from app.session import AgentStatus
+        s.status = AgentStatus.IDLE
+        return s
+
+    async def _make_worker(self, mgr, name="w1", scope="/old/proj"):
+        from tests.conftest import make_backend_mock
+        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+            s = await mgr.create_session(name=name, scope=scope, cwd="/tmp", model="claude-sonnet-4-6")
+        from app.session import AgentStatus
+        s.status = AgentStatus.IDLE
+        return s
+
+    @pytest.mark.asyncio
+    async def test_happy_path_updates_runtime_and_db(self, mgr, tmp_path):
+        from app.db import get_session
+        orch = await self._make_orch(mgr)
+        newdir = tmp_path / "newproj"
+        newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res["ok"] is True
+        assert orch.scope == str(newdir)
+        assert orch.cwd == str(newdir)
+        # mcp env rebuilt with new scope
+        assert orch.mcp_servers["orchestra"]["env"]["ORCHESTRA_SCOPE"] == str(newdir)
+        # db reflects change
+        assert get_session(orch.id)["scope"] == str(newdir)
+        # context preserved
+        assert orch.session_id == "sdk-resume-token"
+
+    @pytest.mark.asyncio
+    async def test_disconnects_backend(self, mgr, tmp_path):
+        orch = await self._make_orch(mgr)
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        orch._disconnect_backend = AsyncMock()
+        await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        orch._disconnect_backend.assert_awaited_once()
+
+    @pytest.mark.asyncio
+    async def test_rejects_when_running(self, mgr, tmp_path):
+        from app.session import AgentStatus
+        orch = await self._make_orch(mgr)
+        orch.status = AgentStatus.RUNNING
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res.get("ok") is not True
+        assert "running" in res["error"].lower()
+
+    @pytest.mark.asyncio
+    async def test_rejects_non_orchestrator(self, mgr, tmp_path):
+        w = await self._make_worker(mgr, name="w1")
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("w1", "/old/proj", str(newdir), str(newdir))
+        assert res.get("ok") is not True
+        assert "orchestrator" in res["error"].lower()
+
+    @pytest.mark.asyncio
+    async def test_rejects_when_live_workers_in_old_scope(self, mgr, tmp_path):
+        orch = await self._make_orch(mgr)
+        await self._make_worker(mgr, name="w1", scope="/old/proj")
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res.get("ok") is not True
+        assert "worker" in res["error"].lower()
+        assert "w1" in res["error"]
+
+    @pytest.mark.asyncio
+    async def test_rejects_nonexistent_cwd(self, mgr):
+        await self._make_orch(mgr)
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", "/new/proj", "/nonexistent/xyz")
+        assert res.get("ok") is not True
+        assert "error" in res
+
+    @pytest.mark.asyncio
+    async def test_not_found(self, mgr, tmp_path):
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("ghost", "/old/proj", str(newdir), str(newdir))
+        assert res.get("ok") is not True
+        assert "not" in res["error"].lower()
+
+    @pytest.mark.asyncio
+    async def test_drains_persist_before_db_write(self, mgr, tmp_path):
+        # fence: any in-flight _persist() must be drained BEFORE change_scope()
+        # so the transaction's cwd write is the last writer (no stale clobber).
+        orch = await self._make_orch(mgr)
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        order = []
+        orch._drain_persist = AsyncMock(side_effect=lambda: order.append("drain"))
+        import app.db as dbmod
+        real_change = dbmod.change_scope
+        def traced(*a, **k):
+            order.append("change_scope")
+            return real_change(*a, **k)
+        with patch("app.db.change_scope", side_effect=traced):
+            res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res["ok"] is True
+        orch._drain_persist.assert_awaited_once()
+        assert order == ["drain", "change_scope"]  # drain strictly before the write
+
+    @pytest.mark.asyncio
+    async def test_db_cwd_is_new_after_inflight_persist(self, mgr, tmp_path):
+        # end-to-end: even with several queued _persist() (old cwd snapshots)
+        # the final DB cwd must be the new one — _drain_persist awaits ALL,
+        # not just the last submitted future.
+        from app.db import get_session
+        orch = await self._make_orch(mgr)
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        orch._persist(); orch._persist(); orch._persist()  # queue stale snapshots
+        assert len(orch._persist_futs) >= 1
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res["ok"] is True
+        assert get_session(orch.id)["cwd"] == str(newdir)
+        # all drained before the transaction → nothing left to clobber
+        assert all(f.done() for f in orch._persist_futs)
+
+
+class TestChangeScopeUnloadedWorkerGuard:
+    @pytest.mark.asyncio
+    async def test_rejects_unloaded_active_worker_in_old_scope(self, mgr, tmp_path):
+        """An active worker row in the DB but NOT in self.sessions must still block."""
+        from tests.conftest import make_backend_mock
+        from app.session import AgentStatus
+        from app.db import save_session, get_session
+        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+            orch = await mgr.create_session(
+                name="orch", scope="/old/proj", cwd="/tmp",
+                model="claude-opus-4-8", is_orchestrator=True,
+            )
+        orch.session_id = "sdk-tok"
+        orch.status = AgentStatus.IDLE
+        # Worker row exists in DB only (not loaded into manager.sessions)
+        save_session({
+            "id": "ghost-worker-id", "name": "ghostw", "scope": "/old/proj",
+            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
+            "status": "idle", "session_id": "x", "cost_usd": 0.0,
+            "worktree_path": None, "branch": None, "is_orchestrator": False,
+            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
+            "finished_at": None, "role": "worker",
+        })
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res.get("ok") is not True
+        assert "ghostw" in res["error"]
+        assert get_session(orch.id)["scope"] == "/old/proj"  # not moved
+
+    @pytest.mark.asyncio
+    async def test_archived_worker_does_not_block(self, mgr, tmp_path):
+        from tests.conftest import make_backend_mock
+        from app.session import AgentStatus
+        from app.db import save_session
+        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+            orch = await mgr.create_session(
+                name="orch", scope="/old/proj", cwd="/tmp",
+                model="claude-opus-4-8", is_orchestrator=True,
+            )
+        orch.session_id = "sdk-tok"
+        orch.status = AgentStatus.IDLE
+        save_session({
+            "id": "dead-worker-id", "name": "deadw", "scope": "/old/proj",
+            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
+            "status": "archived", "session_id": "x", "cost_usd": 0.0,
+            "worktree_path": None, "branch": None, "is_orchestrator": False,
+            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
+            "finished_at": None, "role": "worker",
+        })
+        newdir = tmp_path / "newproj"; newdir.mkdir()
+        res = await mgr.change_orchestrator_scope("orch", "/old/proj", str(newdir), str(newdir))
+        assert res["ok"] is True


## LATER FIX c5fcd36105 (11.6 days later): fix: reset session_id on change-scope — CLI session bound to old cwd, must start fresh
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: reset session_id on change-scope — CLI session bound to old cwd, must start fresh


diff --git a/app/db.py b/app/db.py
index e2f96ba74..b67ed4bba 100644
--- a/app/db.py
+++ b/app/db.py
@@ -511,18 +511,19 @@ def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str)
         name = row["name"]
         clash = c.execute(
             "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
             (name, new_scope, session_id),
         ).fetchone()
         if clash:
             return {"error": f"session '{name}' already exists in scope '{new_scope}'"}
 
+        # Reset session_id — CLI session is bound to old cwd, must start fresh
         cur = c.execute(
-            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
+            "UPDATE sessions SET scope=?, cwd=?, session_id=NULL WHERE id=? AND scope=?",
             (new_scope, new_cwd, session_id, old_scope),
         )
         if cur.rowcount == 0:
             return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}
 
         tm_migrated = False
         target_taken = c.execute("SELECT 1 FROM tm_projects WHERE scope=?", (new_scope,)).fetchone()
         if not target_taken:
diff --git a/app/manager.py b/app/manager.py
index 4eeb388b3..99d389c07 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -686,20 +686,21 @@ class SessionManager:
 
             from app.db import change_scope
             result = change_scope(session.id, old_scope, new_scope, new_cwd)
             if not result.get("ok"):
                 return result
 
             session.scope = new_scope
             session.cwd = new_cwd
+            # CLI session is bound to old cwd — must start fresh in new scope
+            session.session_id = None
             session.mcp_servers = _make_mcp_config(name, new_scope, session.role,
                                                    extra=session.mcp_servers_custom)
-            # No session._persist() here: change_scope() already wrote scope+cwd
-            # synchronously in its transaction (the last writer after the drain).
+            session._persist()
         logger.info(f"Orchestrator '{name}' scope changed: {old_scope} → {new_scope}")
         return result
 
     def _live_workers_in_scope(self, scope: str) -> list[str]:
         """Names of active (idle/running/waiting) workers in scope, from both the
         in-memory registry and the DB (catches unloaded-but-active worker rows).
         Deduplicated by session id."""
         active = ("idle", "running", "waiting")