# Candidate cand-16

## ORIGIN commit e9f76b901b (2026-06-13): #93: enterprise production hardening — skip tunnel/yougile, fix usage/proxy JS
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/main.py b/app/main.py
index 4ec6a4952..25e0f2dd3 100644
--- a/app/main.py
+++ b/app/main.py
@@ -18,36 +18,40 @@ logger = logging.getLogger("orchestra")
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
     from app.models import refresh_models
     await refresh_models()
-    # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
-    from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
+    if not is_auth_enabled():
+        from app import tm_yougile  # noqa: F401 — registers tm sync hooks
     await manager.auto_resume_all()
     from app.bootstrap import ensure_bootstrap
     await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
-    from app.ssh_tunnel import start_tunnel, stop_tunnel
-    await start_tunnel()
+    _tunnel_started = False
+    if not is_auth_enabled():
+        from app.ssh_tunnel import start_tunnel, stop_tunnel
+        await start_tunnel()
+        _tunnel_started = True
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     yield
     snapshot_task.cancel()
-    await stop_tunnel()
+    if _tunnel_started:
+        await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
diff --git a/app/routes/system.py b/app/routes/system.py
index 6c1e91ebf..c324c6f41 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -457,16 +457,18 @@ def _get_agents_cost() -> dict:
             "total_cost_usd_cached": round(total_cached, 4),
             "agents_count": len(agents),
             "agents": agents,
         }
 
 
 @router.get("/api/usage")
 async def get_usage():
+    if is_auth_enabled():
+        return {"usage": None}
     now = time.time()
 
     if _usage_cache["data"] and (now - _usage_cache["ts"]) < _USAGE_CACHE_TTL:
         anthropic_data = _usage_cache["data"]
     else:
         token, refresh_token, _tier = _read_oauth_credentials()
         if not token:
             return JSONResponse({"error": "no OAuth credentials found"}, status_code=500)
@@ -549,16 +551,18 @@ async def _usage_snapshot_loop():
             return
         except Exception as e:
             logger.error(f"usage snapshot error: {e}")
         await asyncio.sleep(SNAPSHOT_INTERVAL)
 
 
 @router.get("/api/usage/history")
 async def usage_history(hours: int = 24):
+    if is_auth_enabled():
+        return []
     from app.db import usage_get_history
     return usage_get_history(hours)
 
 
 # ── Misc ──
 
 @router.post("/api/report_bug")
 async def report_bug_endpoint(req: Request):
diff --git a/app/static/js/app.js b/app/static/js/app.js
index a6ac46a85..64596b5c0 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -88,20 +88,33 @@ document.addEventListener('DOMContentLoaded', () => {
         const path = $('#orch-cwd').value.trim();
         if (path) $('#orch-name').value = autoNameFromPath(path);
     });
     $('#browse-btn')?.addEventListener('click', showProjectPicker);
     initTabContextMenu();
     initHiddenTabsBtn();
     initDropHint();
     $('#restart-btn').addEventListener('click', restartServer);
+    // Enterprise: remove dev-only UI before init binds event listeners
+    if (document.body.dataset.authEnabled === 'true') {
+        document.getElementById('new-orch-btn')?.remove();
+        document.getElementById('new-orch-modal')?.remove();
+        document.querySelector('#proxy-btn')?.parentElement?.remove();
+        document.getElementById('profiles-btn')?.parentElement?.remove();
+        const clientBtn = document.getElementById('client-btn');
+        if (clientBtn) clientBtn.addEventListener('click', openClientModal);
+        const clientClose = document.getElementById('client-modal-close');
+        if (clientClose) clientClose.addEventListener('click', closeClientModal);
+        const clientModal = document.getElementById('client-modal');
+        if (clientModal) clientModal.addEventListener('click', (e) => { if (e.target === clientModal) closeClientModal(); });
+    }
     initProxy();
     initProfilesManager();
-    $('#orch-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
-    $('#orch-cwd').addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
+    $('#orch-name')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
+    $('#orch-cwd')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
     $('#view-prompt-btn').addEventListener('click', openPromptModal);
     $('#compact-btn').addEventListener('click', compactAgent);
     $('#restart-cli-btn').addEventListener('click', restartCli);
     $('#prompt-modal-close').addEventListener('click', closePromptModal);
     $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
     document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); closeClientModal(); } });
     const compactBtn = $('#compact-toggle-btn');
     if (compactBtn) {
@@ -120,28 +133,16 @@ document.addEventListener('DOMContentLoaded', () => {
     }
     const openFolderBtn = $('#open-folder-btn');
     if (openFolderBtn) {
         openFolderBtn.addEventListener('click', () => {
             if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
         });
     }
     loadModels();
-    if (document.body.dataset.authEnabled === 'true') {
-        document.getElementById('new-orch-btn')?.remove();
-        document.getElementById('new-orch-modal')?.remove();
-        document.querySelector('#proxy-btn')?.parentElement?.remove();
-        document.getElementById('profiles-btn')?.parentElement?.remove();
-        const clientBtn = document.getElementById('client-btn');
-        if (clientBtn) clientBtn.addEventListener('click', openClientModal);
-        const clientClose = document.getElementById('client-modal-close');
-        if (clientClose) clientClose.addEventListener('click', closeClientModal);
-        const clientModal = document.getElementById('client-modal');
-        if (clientModal) clientModal.addEventListener('click', (e) => { if (e.target === clientModal) closeClientModal(); });
-    }
     loadOrchestrators();
     scheduleRefresh();
     initFilePreviewModal();
     initUsageBar();
     initHeartbeat();
 });
 
 let eventSource = null;


## LATER FIX 00eff7863f (24.0 days later): Fix: show New Orchestrator button when auth enabled (was hidden by enterprise guard)
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

Fix: show New Orchestrator button when auth enabled (was hidden by enterprise guard)


diff --git a/app/static/js/app.js b/app/static/js/app.js
index f985291ad..21e4f89b3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -91,18 +91,16 @@ document.addEventListener('DOMContentLoaded', () => {
     });
     $('#browse-btn')?.addEventListener('click', showProjectPicker);
     initTabContextMenu();
     initHiddenTabsBtn();
     initDropHint();
     $('#restart-btn').addEventListener('click', restartServer);
     // Enterprise: remove dev-only UI before init binds event listeners
     if (document.body.dataset.authEnabled === 'true') {
-        document.getElementById('new-orch-btn')?.remove();
-        document.getElementById('new-orch-modal')?.remove();
         document.querySelector('#proxy-btn')?.parentElement?.remove();
         document.getElementById('profiles-btn')?.parentElement?.remove();
         const clientBtn = document.getElementById('client-btn');
         if (clientBtn) clientBtn.addEventListener('click', openClientModal);
         const clientClose = document.getElementById('client-modal-close');
         if (clientClose) clientClose.addEventListener('click', closeClientModal);
         const clientModal = document.getElementById('client-modal');
         if (clientModal) clientModal.addEventListener('click', (e) => { if (e.target === clientModal) closeClientModal(); });