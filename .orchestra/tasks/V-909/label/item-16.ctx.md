# Context for item-16

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/main.py b/app/main.py
index 82ac11f61..b7de25ff4 100644
--- a/app/main.py
+++ b/app/main.py
@@ -4,40 +4,42 @@ import asyncio
 import logging
 from contextlib import asynccontextmanager
 
 from fastapi import FastAPI, Request
 from fastapi.responses import JSONResponse, RedirectResponse
 from fastapi.staticfiles import StaticFiles
 from starlette.middleware.base import BaseHTTPMiddleware
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 from app.db import init_db
 from app.deps import manager
 
 logger = logging.getLogger("orchestra")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
+    from app.models import refresh_models
+    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
     from app.ssh_tunnel import start_tunnel, stop_tunnel
     await start_tunnel()
     from app.routes.system import _usage_snapshot_loop
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     yield
     snapshot_task.cancel()
     await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
diff --git a/app/models.py b/app/models.py
index 0e4b38c0d..a4801b9af 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,21 +1,35 @@
-"""Available models — single source of truth."""
+"""Available models — single source of truth.
+
+Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
+fetch_models_from_proxy() replaces them with proxy-only models.
+"""
+
+import logging
+import os
+import re
+
+import httpx
+
+logger = logging.getLogger(__name__)
+
+_proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
     "claude-sonnet-4-6": "Sonnet 4.6",
     "claude-haiku-4-5": "Haiku 4.5",
     "gpt-5.5": "GPT-5.5",
     "gpt-5.4": "GPT-5.4",
     "gpt-5.4-mini": "GPT-5.4 Mini",
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
     "claude-opus-4-6[1m]": 1000000,
     "claude-sonnet-4-6": 200000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
@@ -53,40 +67,168 @@ BACKENDS = {
     "claude-opus-4-6[1m]": "claude",
     "claude-sonnet-4-6": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
 }
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
     "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
     "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
+_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
+
+
+def _generate_aliases(model_id: str) -> list[str]:
+    """Auto-generate short alias candidates for a model ID."""
+    aliases = []
+    if "/" in model_id:
+        tail = model_id.rsplit("/", 1)[1]
+        aliases.append(tail)
+        stripped = _VERSION_RE.sub("", tail)
+        if stripped and stripped != tail:
+            aliases.append(stripped)
+    return aliases
+
+
+def _infer_backend(model_id: str) -> str:
+    if model_id.startswith("gpt-"):
+        return "codex"
+    return "claude"
+
+
+def is_proxy_connected() -> bool:
+    return _proxy_connected
+
+
+async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
+    """Fetch model list from upstream proxy and populate module-level dicts.
+
+    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
+    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
+    """
+    global _proxy_connected
+    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
+    url = f"{base_url.rstrip('/')}/v1/models"
+
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+
+    try:
+        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
+            resp = await client.get(
+                url,
+                headers={"Authorization": f"Bearer {api_key}"},
+            )
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as e:
+        logger.warning(f"fetch_models_from_proxy failed: {e}")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    models_list = data.get("data", [])
+    if not models_list:
+        logger.warning("fetch_models_from_proxy: empty model list")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    if enterprise_mode:
+        MODELS.clear()
+        CONTEXT_LIMITS.clear()
+        TOKEN_PRICES.clear()
+        BACKENDS.clear()
+        ALIASES.clear()
+
+    added = 0
+    for m in models_list:
+        mid = m.get("id", "")
+        if not mid:
+            continue
+
+        if "/" in mid:
+            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
+        else:
+            label = mid.replace("-", " ").title()
+
+        ctx = m.get("context_length") or 200000
+
+        pricing = m.get("pricing", {})
+        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
+        completion_price = float(pricing.get("completion", "0")) * 1_000_000
+
+        backend = _infer_backend(mid)
+
+        if mid not in MODELS:
+            MODELS[mid] = label
+            added += 1
+        if mid not in CONTEXT_LIMITS:
+            CONTEXT_LIMITS[mid] = ctx
+        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
+            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
+        if mid not in BACKENDS:
+            BACKENDS[mid] = backend
+
+        for alias in _generate_aliases(mid):
+            if alias not in ALIASES and alias != mid:
+                ALIASES[alias] = mid
+
+    _proxy_connected = True
+    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
+    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
+    return True
+
+
+async def refresh_models() -> None:
+    """Startup helper — fetch models, enterprise-aware."""
+    from app.auth import is_auth_enabled
+    enterprise = is_auth_enabled()
+    ok = await fetch_models_from_proxy(enterprise_mode=enterprise)
+    if ok:
+        logger.info(f"Models ready: {len(MODELS)} total (proxy_connected=True)")
+    else:
+        if enterprise:
+            logger.warning(f"Proxy unreachable in enterprise mode — 0 models available")
+        else:
+            logger.warning(f"Proxy unreachable, using {len(MODELS)} hardcoded models")
+
 
 def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
     if m in MODELS:
         return m
     return model
 
 
 def backend_for_model(model: str) -> str:
     return BACKENDS.get(model, "claude")
 
 
 def available_models_block() -> str:
     """Prompt block listing all available models for spawn_worker."""
     lines = ["## Available models for spawn_worker(model=...)"]
     for model_id, label in MODELS.items():
         ctx = CONTEXT_LIMITS.get(model_id, 200000)
         ctx_k = f"{ctx // 1000}k"
diff --git a/app/routes/system.py b/app/routes/system.py
index 0ae9db0e2..c7e195e53 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -2,41 +2,41 @@
 orchestrators, test-lock, git-status, restart, GitHub webhook."""
 
 import asyncio
 import hashlib
 import hmac
 import json
 import logging
 import os
 import re
 import time
 from pathlib import Path
 from typing import Optional
 
 from fastapi import APIRouter, Request, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
 from pydantic import BaseModel
 
 from app.auth import is_auth_enabled
 from app.db import get_all_sessions, list_profiles, upsert_profile, delete_profile
 from app.deps import manager, templates
-from app.models import MODELS
+from app.models import MODELS, CONTEXT_LIMITS, TOKEN_PRICES, is_proxy_connected
 from app.pipeline import list_pipelines
 
 logger = logging.getLogger("orchestra.system")
 
 router = APIRouter()
 
 
 class ProfileRequest(BaseModel):
     """Тело запроса для создания/обновления профиля Claude."""
     name: str
     config_dir: str = ""
 
 
 class TestLockRequest(BaseModel):
     scope: str
     holder: str
     reason: str = ""
 
 
 class ChangeScopeRequest(BaseModel):
@@ -319,41 +319,52 @@ async def create_profile(req: ProfileRequest):
         warning = (
             f"config_dir '{config_dir}' не существует — будет создан CLI "
             "или приведёт к ошибке при запуске"
         )
     upsert_profile(req.name, config_dir)
     return {"profiles": list_profiles(), "warning": warning}
 
 
 @router.delete("/api/profiles/{name}")
 async def remove_profile(name: str):
     """Удалить профиль. Сид-профиль ``personal`` защищён → 409."""
     try:
         delete_profile(name)
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=409)
     return list_profiles()
 
 
 @router.get("/api/models")
 async def list_models():
-    return [{"id": k, "name": v} for k, v in MODELS.items()]
+    models = []
+    for mid, name in MODELS.items():
+        entry = {"id": mid, "name": name}
+        ctx = CONTEXT_LIMITS.get(mid)
+        if ctx:
+            entry["context_length"] = ctx
+        prices = TOKEN_PRICES.get(mid)
+        if prices:
+            entry["price_input"] = prices["input"]
+            entry["price_output"] = prices["output"]
+        models.append(entry)
+    return {"models": models, "proxy_connected": is_proxy_connected()}
 
 
 @router.get("/api/stats")
 async def stats(scope: Optional[str] = None):
     return manager.stats(scope)
 
 
 # ── Usage (Anthropic OAuth) ──
 
 _USAGE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "usage_cache.json"
 _usage_cache: dict = {"data": None, "ts": 0.0, "token": None}
 _USAGE_CACHE_TTL = 300
 _CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
 
 
 def _load_usage_cache():
     if _USAGE_CACHE_FILE.exists():
         try:
             cached = json.loads(_USAGE_CACHE_FILE.read_text())
             _usage_cache["data"] = cached.get("data")
diff --git a/app/static/js/app.js b/app/static/js/app.js
index dce523d62..a4595330c 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -230,49 +230,53 @@ async function loadMoreLogs() {
         const anchor = chat.firstChild;
         for (const l of logs) {
             addChatEntry(l.type, l.content, l.ts, anchor);
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                 chatLogs[selectedAgent].firstId = l.id;
             }
         }
         chat.scrollTop = chat.scrollHeight - oldHeight;
         updateLoadMoreBtn();
     } catch (e) {
         if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
         console.warn('loadMoreLogs error:', e);
     }
 }
 
 
 // === Models ===
 async function loadModels() {
     try {
-        const models = await api('/api/models');
+        const data = await api('/api/models');
+        const models = data.models || [];
         const select = $('#orch-model');
-        select.innerHTML = '';
-        for (const m of models) {
-            const opt = document.createElement('option');
-            opt.value = m.id;
-            opt.textContent = `${m.name} (${m.id})`;
-            select.appendChild(opt);
+        if (select) {
+            select.innerHTML = '';
+            for (const m of models) {
+                const opt = document.createElement('option');
+                opt.value = m.id;
+                opt.textContent = `${m.name} (${m.id})`;
+                select.appendChild(opt);
+            }
         }
+        _updateProxyStatus(data.proxy_connected);
     } catch {}
 }
 
 // === Profile / Pipeline / Role dropdowns (модалка создания корня) ===
 let _pipelineRoles = {};  // карта pipeline-name → [roles]
 
 async function loadProfilesDropdown() {
     try {
         const profiles = await api('/api/profiles');
         const select = $('#orch-profile');
         select.innerHTML = '';
         for (const p of profiles) {
             const opt = document.createElement('option');
             opt.value = p.name;
             opt.textContent = `${p.name} (${p.config_dir || 'env процесса'})`;
             select.appendChild(opt);
         }
         // API sorts by name (ORDER BY name), so first entry ≠ 'personal'.
         // Prefer 'personal' explicitly; fall back to whatever comes first.
         const def = profiles.find(p => p.name === 'personal') || profiles[0];
@@ -1113,45 +1117,57 @@ function updateInputState() {
     const isDead = agentEl && (agentEl.classList.contains('opacity-50'));
     if (isDead) {
         input.placeholder = `${selectedAgent} — archived (read-only)`;
         input.disabled = true;
         btn.disabled = true;
     } else {
         input.placeholder = `Message ${selectedAgent}...`;
         input.disabled = false;
         btn.disabled = false;
     }
 }
 
 let contextCache = {};
 let agentColors = {};
 
 let _MODELS = [];
 let _modelsLoaded = false;
 async function _ensureModels() {
     if (_modelsLoaded) return;
     try {
-        const models = await api('/api/models');
+        const data = await api('/api/models');
+        const models = data.models || [];
         _MODELS = models.map(m => ({ id: m.id, label: m.name }));
         _modelsLoaded = true;
     } catch {}
 }
+function _updateProxyStatus(connected) {
+    const el = document.getElementById('proxy-status');
+    if (!el) return;
+    if (connected) {
+        el.textContent = '🟢';
+        el.title = 'Proxy connected';
+    } else {
+        el.textContent = '🔴';
+        el.title = 'Proxy offline — no models available';
+    }
+}
 async function _showModelPicker(agentName, currentModel, anchor) {
     const existing = document.getElementById('model-picker-dd');
     if (existing) { existing.remove(); return; }
     await _ensureModels();
     const dd = document.createElement('div');
     dd.id = 'model-picker-dd';
     const rect = anchor.getBoundingClientRect();
     dd.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.bottom + 4}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
     for (const m of _MODELS) {
         const item = document.createElement('div');
         const isCurrent = currentModel === m.id;
         item.style.cssText = `padding:5px 14px;font-size:11px;color:${isCurrent ? '#818cf8' : '#94a3b8'};cursor:${isCurrent ? 'default' : 'pointer'};white-space:nowrap`;
         item.textContent = `${isCurrent ? '● ' : ''}${m.label}`;
         if (!isCurrent) {
             item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
             item.addEventListener('mouseleave', () => item.style.background = '');
             item.addEventListener('click', async () => {
                 dd.remove();
                 try {
                     await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
@@ -4140,49 +4156,89 @@ function initHeartbeat() {
 }
 
 // === Tasks Panel ===
 let _tasksTabActive = false;
 let _tasksInterval = null;
 
 let _jobsTabActive = false;
 let _jobsInterval = null;
 
 function switchLeftTab(tab) {
     const fileTree = document.getElementById('file-tree');
     const tasksPanel = document.getElementById('tasks-panel');
     const jobsPanel = document.getElementById('jobs-panel');
     document.querySelectorAll('.left-tab').forEach(btn => {
         const isActive = btn.dataset.leftTab === tab;
         btn.classList.toggle('text-white', isActive);
         btn.classList.toggle('border-indigo-500', isActive);
         btn.classList.toggle('text-slate-500', !isActive);
         btn.classList.toggle('border-transparent', !isActive);
     });
+    const clientPanel = document.getElementById('client-panel');
     if (fileTree) fileTree.classList.toggle('hidden', tab !== 'files');
     if (tasksPanel) tasksPanel.classList.toggle('hidden', tab !== 'tasks');
     if (jobsPanel) jobsPanel.classList.toggle('hidden', tab !== 'jobs');
+    if (clientPanel) clientPanel.classList.toggle('hidden', tab !== 'client');
     _tasksTabActive = tab === 'tasks';
     _jobsTabActive = tab === 'jobs';
     if (_tasksTabActive) { loadTasks(); if (!_tasksInterval) _tasksInterval = setInterval(loadTasks, 5000); }
     else { if (_tasksInterval) { clearInterval(_tasksInterval); _tasksInterval = null; } }
     if (_jobsTabActive) { loadJobs(); if (!_jobsInterval) _jobsInterval = setInterval(loadJobs, 10000); }
     else { if (_jobsInterval) { clearInterval(_jobsInterval); _jobsInterval = null; } }
+    if (tab === 'client') loadClientInfo();
+}
+
+async function loadClientInfo() {
+    const panel = document.getElementById('client-panel');
+    if (!panel) return;
+    panel.innerHTML = '<span class="text-slate-500">Loading...</span>';
+    try {
+        const data = await api('/api/models');
+        const models = data.models || [];
+        const connected = data.proxy_connected;
+        const currency = document.body.dataset.currency || '$';
+        let html = `<div class="space-y-3">`;
+        html += `<div class="flex items-center gap-2 mb-2">
+            <span class="text-sm font-bold text-white">Client Info</span>
+            <span class="text-xs ${connected ? 'text-emerald-400' : 'text-red-400'}">${connected ? '🟢 Proxy connected' : '🔴 Proxy offline'}</span>
+        </div>`;
+        if (!models.length) {
+            html += `<div class="text-slate-500 italic">No models available</div>`;
+        } else {
+            html += `<div class="text-xs text-slate-500 mb-1">${models.length} models available</div>`;
+            for (const m of models) {
+                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k ctx` : '';
+                const price = (m.price_input != null && m.price_output != null)
+                    ? `${currency}${m.price_input}/M in · ${currency}${m.price_output}/M out`
+                    : '';
+                html += `<div class="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
+                    <div class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</div>
+                    <div class="text-[10px] text-slate-500 font-mono">${escHtml(m.id)}</div>
+                    <div class="text-[10px] text-slate-400 mt-0.5">${[ctx, price].filter(Boolean).join(' · ')}</div>
+                </div>`;
+            }
+        }
+        html += `</div>`;
+        panel.innerHTML = html;
+    } catch (e) {
+        panel.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
+    }
 }
 
 const STATUS_ORDER = ['in_progress', 'done', 'new', 'backlog', 'paid', 'cancelled'];
 const STATUS_COLORS = {
     in_progress: 'bg-blue-400', done: 'bg-amber-400', new: 'bg-white',
     backlog: 'bg-slate-500', paid: 'bg-emerald-400', cancelled: 'bg-red-400',
 };
 const STATUS_LABELS = {
     in_progress: 'IN PROGRESS', done: 'DONE', new: 'NEW',
     backlog: 'BACKLOG', paid: 'PAID', cancelled: 'CANCELLED',
 };
 // These statuses are collapsed by default — they're historical/archive, not actionable
 const COLLAPSED_DEFAULT = new Set(['backlog', 'paid', 'cancelled']);
 let _taskCollapsed = {};
 
 async function loadTasks() {
     const panel = document.getElementById('tasks-panel');
     if (!panel) return;
     try {
         const scope = currentScope || '';
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index c7dc8b35c..5d30665d3 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -7,40 +7,41 @@
     <script src="/static/css/vendor/tailwind.js"></script>
     <script src="/static/css/vendor/marked.min.js"></script>
     <script src="/static/css/vendor/purify.min.js"></script>
     <script src="/static/css/vendor/diff_match_patch.js"></script>
     <script src="/static/css/vendor/highlight.min.js"></script>
     <link rel="stylesheet" href="/static/css/vendor/highlight-github-dark.min.css">
     <link rel="stylesheet" href="/static/css/style.css">
 </head>
 <body class="h-screen flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}">
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
             <h1 class="text-lg font-bold tracking-tight shrink-0">🎼</h1>
             <div id="orch-tabs" class="flex items-center gap-1.5 overflow-x-auto no-scrollbar"></div>
             <select id="orch-picker" class="hidden"></select>
             <button id="new-orch-btn" class="px-2.5 py-1.5 bg-slate-800/50 hover:bg-slate-700 border border-dashed border-slate-700 rounded-full text-xs transition-colors shrink-0" title="New orchestrator">+</button>
             <button id="hidden-tabs-btn" class="px-2 py-1.5 hover:bg-slate-700 rounded-full text-xs transition-colors text-slate-500 hover:text-slate-300 shrink-0 hidden" title="Show hidden tabs">👁</button>
         </div>
         <div class="flex items-center gap-3 text-xs text-slate-600 shrink-0">
             <span id="stats-line"></span>
+            {% if is_auth_enabled %}<span id="proxy-status" class="text-xs cursor-default" title="Proxy status">⏳</span>{% endif %}
             <div class="relative">
                 <button id="proxy-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400 flex items-center gap-1" title="Proxy settings">
                     <span id="proxy-flag">🌐</span>
                     <span id="proxy-ip" class="text-[10px] text-slate-500"></span>
                 </button>
                 <div id="proxy-dropdown" class="absolute right-0 top-full mt-1 w-[320px] glass glow rounded-xl p-3 z-50 hidden">
                     <div class="flex items-center justify-between mb-2">
                         <span class="text-xs font-bold text-white">🌐 Proxy</span>
                         <button id="proxy-check-all" class="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors">Check All</button>
                     </div>
                     <div id="proxy-list" class="space-y-1.5"></div>
                 </div>
             </div>
             <div class="relative">
                 <button id="profiles-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400" title="Profiles">🗂</button>
                 <div id="profiles-dropdown" class="absolute right-0 top-full mt-1 w-[320px] glass glow rounded-xl p-3 z-50 hidden">
                     <div class="flex items-center justify-between mb-2">
                         <span class="text-xs font-bold text-white">🗂 Claude Profiles</span>
                     </div>
                     <div id="profiles-list" class="space-y-1.5 mb-2"></div>
@@ -140,45 +141,47 @@
 
     <!-- Prompt Modal -->
     <div id="prompt-modal" class="fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm z-50 items-center justify-center hidden">
       <div class="glass glow rounded-xl p-6 w-[90vw] max-w-4xl max-h-[85vh] flex flex-col">
         <div class="flex justify-between items-center mb-3">
           <span id="prompt-modal-name" class="text-indigo-300 font-bold text-sm"></span>
           <button id="prompt-modal-close" class="text-slate-400 hover:text-white text-lg">✕</button>
         </div>
         <div id="prompt-modal-body" class="flex-1 overflow-auto text-xs text-slate-300 markdown-body bg-[#0f172a] rounded-lg p-4 border border-slate-800"></div>
       </div>
     </div>
 
     <!-- Main Layout -->
     <div class="flex flex-1 overflow-hidden">
         <!-- Left Panel (Files / Tasks tabs) -->
         <div id="file-panel" class="w-[250px] border-r border-slate-800/50 flex flex-col overflow-hidden">
             <div class="flex border-b border-slate-800/50">
                 <button data-left-tab="files" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-white border-b-2 border-indigo-500 transition-colors" onclick="switchLeftTab('files')">FILES</button>
                 <button data-left-tab="tasks" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('tasks')">TASKS</button>
                 <button data-left-tab="jobs" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('jobs')">JOBS</button>
+                {% if is_auth_enabled %}<button data-left-tab="client" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('client')">CLIENT</button>{% endif %}
                 <button id="open-folder-btn" title="Open in file manager" style="background:none;border:none;cursor:pointer;font-size:14px;opacity:0.5;padding:2px;transition:opacity 0.15s" onmouseenter="this.style.opacity='0.9'" onmouseleave="this.style.opacity='0.5'">📂</button>
             </div>
             <div id="file-tree" class="flex-1 overflow-y-auto text-xs p-1"></div>
             <div id="tasks-panel" class="flex-1 overflow-y-auto text-xs p-1 hidden"></div>
             <div id="jobs-panel" class="flex-1 overflow-y-auto text-xs p-1 hidden"></div>
+            {% if is_auth_enabled %}<div id="client-panel" class="flex-1 overflow-y-auto text-xs p-2 hidden"></div>{% endif %}
         </div>
 
         <!-- Chat -->
         <div class="flex-1 flex flex-col min-w-0">
             <div id="chat" class="flex-1 overflow-y-auto overflow-x-hidden p-4 space-y-2"></div>
             <div class="p-3 border-t border-slate-800/50">
                 <div id="input-resize-handle" style="height:6px;cursor:row-resize;margin:0 auto 4px;width:40px;border-radius:3px;background:rgba(51,65,85,0.3)"></div>
                 <div class="flex gap-2">
                     <textarea id="chat-input" rows="2" placeholder="Message..."
                         class="flex-1 px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm resize-none focus:border-indigo-500 focus:outline-none transition-colors"
                         style="min-height:40px;max-height:300px"></textarea>
                     <div class="flex flex-col gap-1 self-end">
                         <button id="stop-btn" class="px-4 py-2 bg-red-900 hover:bg-red-800 rounded-lg text-sm font-medium transition-colors hidden">Stop</button>
                         <button id="send-btn" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium transition-colors">Send</button>
                     </div>
                 </div>
             </div>
         </div>
 
         <!-- Right Panel -->


## Later history of the touched files on main (after this commit)

368 later commits touch these paths; the first 40 (oldest first):
cbe4f00b0 2026-06-13 Revert "#91: client info page + proxy-only models + connection indicator"
9d7ba03ed 2026-06-13 prompt modal: all blocks open by default, tag-specific colors (role=green, rules=red, module=blue, dynamic=yellow)
79cc3fa0f 2026-06-13 #91: #91: client info page + proxy-only models + connection indicator
d0bf04778 2026-06-13 #92: enterprise cleanup — hide dev UI, client info modal
cde3ca0cd 2026-06-13 #92: backend 403 block on proxy/profiles/tunnel API for enterprise
a1c89c427 2026-06-13 #88: restore auto-bootstrap (lost in revert)
2364a9e25 2026-06-13 #91: fix proxy URL — read ANTHROPIC_BASE_URL (set in container .env)
200d6c33c 2026-06-13 #91: semantic aliases for dynamic models (opus/sonnet/deepseek) + resolve warning
920f7d9f3 2026-06-13 fix: model dropdown sync + resolve_model fallback to first available
b196f3e6f 2026-06-13 fix: model picker click — stopPropagation + reload sessions after change
e9f76b901 2026-06-13 #93: enterprise production hardening — skip tunnel/yougile, fix usage/proxy JS
f38cd69c7 2026-06-13 #94: auto-retry proxy + client modal improvements + refresh button
12b7b6594 2026-06-13 fix: dynamic cost precision — show $0.001 not $0.00 for cheap models
3651919d7 2026-06-14 #96 phase 2: route non-Claude/non-GPT models to opencode backend
fc207ec3a 2026-06-14 fix: user message duplicate — skip SSE echo when bubble already finalized
67b2c86a7 2026-06-14 fix: hide prompt injection (Orchestra platform note) from chat display
cb072944c 2026-06-14 fix: opencode.json gitignore + git config + file browser deny + user message dedup
ded9b9242 2026-06-14 fix: 6 UX issues — .claude gitignore, no reconnect for opencode, cost precision, dedup, tool truncate
28e29048f 2026-06-15 show agent role next to model in sidebar (skip default 'worker')
e16055f6f 2026-06-15 Revert "show agent role next to model in sidebar (skip default 'worker')"
ef292e6a0 2026-06-15 show role badge in spawn_worker tool (dashboard + TG)
c0c2ff861 2026-06-15 #80: #80: prompt view by source — files, modules, dynamic, skills
bc0d3c343 2026-06-15 fix: missing modules in orchestrator, duplicate colors, clipboard on HTTP
774c359b1 2026-06-15 fix: delay SSE reconnect on agent switch — prevents losing in-flight messages
b5b7890c1 2026-06-15 fix: hardcode role=orchestrator for New Orchestrator — hidden dropdown was picking random role
d31f3d483 2026-06-16 fix: render SVG files as images in file preview, not raw XML
fc25e1a45 2026-06-17 feat: beautiful Glob rendering on dashboard — matching Read/Grep style
1fe4ce175 2026-06-17 #82: #82: fix SSE race condition on agent switch
d40686f26 2026-06-19 fix: clear localMessages/pendingBubble on agent switch — prevents message dedup across agents
f31e5b8ad 2026-06-19 fix: send message timeout 15s instead of 5s, silently ignore timeout errors (POST likely delivered)
9dc240151 2026-06-21 #83: feat(#83): real-time token streaming in dashboard
dc8a2642d 2026-06-21 #84: #84: smooth streaming animation + typing cursor
514a791b8 2026-06-21 #84: #84: typewriter streaming animation
eeea9b7ae 2026-06-23 fix: insert non-stream messages before streaming bubble instead of finalizing it
bd2a60a99 2026-06-29 #86: #86: usage analytics modal with cost charts and rate limits
7ebe48c67 2026-06-29 fix: stop cleaning usage_snapshots — keep all history
1f5001124 2026-06-29 #86: #86: real per-day cost analytics from turn logs
dc3be906d 2026-06-30 fix: proxy persistence + hot-switch + lowercase env leak
ada728e9b 2026-07-01 fix(proxy): kill zombie ssh tunnels + dashboard status TTL
21b7a2a72 2026-07-01 refactor: remove Opus 4.6, redirect all aliases to 4.8

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### cbe4f00b0 Revert "#91: client info page + proxy-only models + connection indicator"

diff --git a/app/main.py b/app/main.py
index b7de25ff4..82ac11f61 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,12 +19,10 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
-    from app.models import refresh_models
-    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
diff --git a/app/models.py b/app/models.py
index a4801b9af..0e4b38c0d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,20 +1,6 @@
-"""Available models — single source of truth.
-
-Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
-fetch_models_from_proxy() replaces them with proxy-only models.
-"""
-
-import logging
-import os
-import re
-
-import httpx
-
-logger = logging.getLogger(__name__)
-
-_proxy_connected: bool = False
+"""Available models — single source of truth."""
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -82,138 +68,10 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
-_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
-
-
-def _generate_aliases(model_id: str) -> list[str]:
-    """Auto-generate short alias candidates for a model ID."""
-    aliases = []
-    if "/" in model_id:
-        tail = model_id.rsplit("/", 1)[1]
-        aliases.append(tail)
-        stripped = _VERSION_RE.sub("", tail)
-        if stripped and stripped != tail:
-            aliases.append(stripped)
-    return aliases
-
-
-def _infer_backend(model_id: str) -> str:
-    if model_id.startswith("gpt-"):
-        return "codex"
-    return "claude"
-
-
-def is_proxy_connected() -> bool:
-    return _proxy_connected
-
-
-async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
-    """Fetch model list from upstream proxy and populate module-level dicts.
-
-    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
-    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
-    """
-    global _proxy_connected
-    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
-    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
-    url = f"{base_url.rstrip('/')}/v1/models"
-
-    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
-
-    try:
-        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
-            resp = await client.get(
-                url,
-                headers={"Authorization": f"Bearer {api_key}"},
-            )
-            resp.raise_for_status()
-            data = resp.json()
-    except Exception as e:
-        logger.warning(f"fetch_models_from_proxy failed: {e}")
-        _proxy_connected = False
-        if enterprise_mode:
-            MODELS.clear()
-            CONTEXT_LIMITS.clear()
-            TOKEN_PRICES.clear()
-            BACKENDS.clear()
-            ALIASES.clear()
-        return False
-
-    models_list = data.get("data", [])
-    if not models_list:
-        logger.warning("fetch_models_from_proxy: empty model list")
-        _proxy_connected = False
-        if enterprise_mode:
-            MODELS.clear()
-            CONTEXT_LIMITS.clear()
-            TOKEN_PRICES.clear()
-            BACKENDS.clear()
-            ALIASES.clear()
-        return False
-
-    if enterprise_mode:
-        MODELS.clear()
-        CONTEXT_LIMITS.clear()
-        TOKEN_PRICES.clear()
-        BACKENDS.clear()
-        ALIASES.clear()
-
-    added = 0
-    for m in models_list:
-        mid = m.get("id", "")
-        if not mid:
-            continue
-
-        if "/" in mid:
-            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
-        else:
-            label = mid.replace("-", " ").title()
-
-        ctx = m.get("context_length") or 200000
-
-        pricing = m.get("pricing", {})
-        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
-        completion_price = float(pricing.get("completion", "0")) * 1_000_000
-
-        backend = _infer_backend(mid)
-
-        if mid not in MODELS:
-            MODELS[mid] = label
-            added += 1
-        if mid not in CONTEXT_LIMITS:
### 9d7ba03ed prompt modal: all blocks open by default, tag-specific colors (role=green, rules=red, module=blue, dynamic=yellow)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index dce523d62..dc982e547 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -381,12 +381,27 @@ async function openPromptModal() {
         body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
     }
 }
 
 function _renderPromptBlocks(container, blocks) {
-    const TYPE_COLORS = { static: '#3b82f6', dynamic: '#f59e0b', skill: '#22c55e' };
-    const TYPE_LABELS = { static: 'file', dynamic: 'dynamic', skill: 'skill' };
+    // Tag-specific colors for better visual distinction
+    const TAG_COLORS = {
+        platform: '#64748b', role: '#22c55e', rules: '#ef4444',
+        'git-workflow': '#38bdf8', orchestration: '#7c3aed', 'task-workflow': '#7c3aed',
+        'decision-tree': '#7c3aed', tools: '#7c3aed', 'worker-management': '#7c3aed',
+        workflow: '#7c3aed', 'background-jobs': '#f97316', 'task-management': '#f97316',
+        'mcp-tools': '#64748b', pricing: '#fbbf24', memory: '#64748b',
+        'report-format': '#38bdf8', section: '#f59e0b', text: '#f59e0b',
+    };
+    const TAG_LABELS = {
+        platform: 'platform', role: 'role', rules: 'rules',
+        'git-workflow': 'module', orchestration: 'module', 'background-jobs': 'module',
+        'task-management': 'module', 'mcp-tools': 'platform', 'report-format': 'module',
+        'decision-tree': 'orchestration', tools: 'orchestration', 'task-workflow': 'orchestration',
+        'worker-management': 'orchestration', workflow: 'orchestration',
+        pricing: 'dynamic', memory: 'rules', section: 'dynamic', text: 'dynamic',
+    };
     const staticN = blocks.filter(b => b.type === 'static').length;
     const dynN = blocks.filter(b => b.type === 'dynamic').length;
     const totalChars = blocks.reduce((s, b) => s + (b.size || 0), 0);
     const totalTokens = Math.round(totalChars / 4);
 
@@ -396,15 +411,16 @@ function _renderPromptBlocks(container, blocks) {
         <span class="pb-stat" style="color:#f59e0b"><b>${dynN}</b> dynamic</span>
         <span class="pb-stat"><b>~${totalTokens >= 1000 ? (totalTokens/1000).toFixed(1)+'k' : totalTokens}</b> tokens</span>
     </div>`;
 
     blocks.forEach((b, i) => {
-        const color = TYPE_COLORS[b.type] || '#64748b';
-        const label = TYPE_LABELS[b.type] || b.type;
+        const color = TAG_COLORS[b.tag] || (b.type === 'dynamic' ? '#f59e0b' : '#3b82f6');
+        const label = TAG_LABELS[b.tag] || b.type;
         const tokens = Math.round((b.size || 0) / 4);
         const tokStr = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
-        html += `<div class="pb-block" style="border-left-color:${color}" data-pb-idx="${i}">
+        // All blocks open by default
+        html += `<div class="pb-block pb-open" style="border-left-color:${color}" data-pb-idx="${i}">
             <div class="pb-header" onclick="this.parentElement.classList.toggle('pb-open')">
                 <span class="pb-chevron">▸</span>
                 <span class="pb-tag" style="background:${color}22;color:${color}">${label}</span>
                 <span class="pb-title">${escHtml(b.title)}</span>
                 <span class="pb-meta">${tokStr} tok</span>
@@ -413,14 +429,19 @@ function _renderPromptBlocks(container, blocks) {
             <div class="pb-body"></div>
         </div>`;
     });
     container.innerHTML = html;
 
+    // Load all content immediately since blocks are open by default
     container.querySelectorAll('.pb-block').forEach((el, i) => {
         const b = blocks[i];
+        const bodyEl = el.querySelector('.pb-body');
+        if (b.content) {
+            bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
+            bodyEl.dataset.loaded = '1';
+        }
         el.querySelector('.pb-header').addEventListener('click', () => {
-            const bodyEl = el.querySelector('.pb-body');
             if (!bodyEl.dataset.loaded && b.content) {
                 bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
                 bodyEl.dataset.loaded = '1';
             }
         });
### 79cc3fa0f #91: #91: client info page + proxy-only models + connection indicator

diff --git a/app/main.py b/app/main.py
index 82ac11f61..b7de25ff4 100644
--- a/app/main.py
+++ b/app/main.py
@@ -19,10 +19,12 @@ logger = logging.getLogger("orchestra")
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
+    from app.models import refresh_models
+    await refresh_models()
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
diff --git a/app/models.py b/app/models.py
index 0e4b38c0d..a4801b9af 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,6 +1,20 @@
-"""Available models — single source of truth."""
+"""Available models — single source of truth.
+
+Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
+fetch_models_from_proxy() replaces them with proxy-only models.
+"""
+
+import logging
+import os
+import re
+
+import httpx
+
+logger = logging.getLogger(__name__)
+
+_proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -68,10 +82,138 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
+_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
+
+
+def _generate_aliases(model_id: str) -> list[str]:
+    """Auto-generate short alias candidates for a model ID."""
+    aliases = []
+    if "/" in model_id:
+        tail = model_id.rsplit("/", 1)[1]
+        aliases.append(tail)
+        stripped = _VERSION_RE.sub("", tail)
+        if stripped and stripped != tail:
+            aliases.append(stripped)
+    return aliases
+
+
+def _infer_backend(model_id: str) -> str:
+    if model_id.startswith("gpt-"):
+        return "codex"
+    return "claude"
+
+
+def is_proxy_connected() -> bool:
+    return _proxy_connected
+
+
+async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
+    """Fetch model list from upstream proxy and populate module-level dicts.
+
+    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
+    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
+    """
+    global _proxy_connected
+    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
+    url = f"{base_url.rstrip('/')}/v1/models"
+
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+
+    try:
+        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
+            resp = await client.get(
+                url,
+                headers={"Authorization": f"Bearer {api_key}"},
+            )
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as e:
+        logger.warning(f"fetch_models_from_proxy failed: {e}")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    models_list = data.get("data", [])
+    if not models_list:
+        logger.warning("fetch_models_from_proxy: empty model list")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    if enterprise_mode:
+        MODELS.clear()
+        CONTEXT_LIMITS.clear()
+        TOKEN_PRICES.clear()
+        BACKENDS.clear()
+        ALIASES.clear()
+
+    added = 0
+    for m in models_list:
+        mid = m.get("id", "")
+        if not mid:
+            continue
+
+        if "/" in mid:
+            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
+        else:
+            label = mid.replace("-", " ").title()
+
+        ctx = m.get("context_length") or 200000
+
+        pricing = m.get("pricing", {})
+        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
+        completion_price = float(pricing.get("completion", "0")) * 1_000_000
+
+        backend = _infer_backend(mid)
+
+        if mid not in MODELS:
+            MODELS[mid] = label
+            added += 1
+        if mid not in CONTEXT_LIMITS:
### d0bf04778 #92: enterprise cleanup — hide dev UI, client info modal

diff --git a/app/routes/system.py b/app/routes/system.py
index c7e195e53..4c488230d 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -51,10 +51,11 @@ class ChangeScopeRequest(BaseModel):
 async def dashboard(request: Request):
     return templates.TemplateResponse(request, "dashboard.html", {
         "currency_symbol": os.getenv("CURRENCY_SYMBOL", "₽"),
         "hide_thinking": is_auth_enabled(),
         "is_auth_enabled": is_auth_enabled(),
+        "client_name": os.getenv("CLIENT_NAME", "Client"),
     })
 
 
 @router.get("/login", response_class=HTMLResponse)
 async def login_page(request: Request):
@@ -348,10 +349,17 @@ async def list_models():
             entry["price_output"] = prices["output"]
         models.append(entry)
     return {"models": models, "proxy_connected": is_proxy_connected()}
 
 
+@router.post("/api/models/refresh")
+async def refresh_models_endpoint():
+    from app.models import refresh_models
+    await refresh_models()
+    return {"ok": True, "proxy_connected": is_proxy_connected(), "model_count": len(MODELS)}
+
+
 @router.get("/api/stats")
 async def stats(scope: Optional[str] = None):
     return manager.stats(scope)
 
 
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 78ae06ed5..81ec482b3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -100,11 +100,11 @@ document.addEventListener('DOMContentLoaded', () => {
     $('#view-prompt-btn').addEventListener('click', openPromptModal);
     $('#compact-btn').addEventListener('click', compactAgent);
     $('#restart-cli-btn').addEventListener('click', restartCli);
     $('#prompt-modal-close').addEventListener('click', closePromptModal);
     $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
-    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); } });
+    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); closeClientModal(); } });
     const compactBtn = $('#compact-toggle-btn');
     if (compactBtn) {
         compactBtn.textContent = window.compactMode ? '📄' : '📋';
         compactBtn.title = window.compactMode ? 'Switch to normal view' : 'Switch to compact view';
         compactBtn.addEventListener('click', () => {
@@ -123,10 +123,22 @@ document.addEventListener('DOMContentLoaded', () => {
         openFolderBtn.addEventListener('click', () => {
             if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
         });
     }
     loadModels();
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
     loadOrchestrators();
     scheduleRefresh();
     initFilePreviewModal();
     initUsageBar();
     initHeartbeat();
@@ -4192,60 +4204,80 @@ function switchLeftTab(tab) {
         btn.classList.toggle('text-white', isActive);
         btn.classList.toggle('border-indigo-500', isActive);
         btn.classList.toggle('text-slate-500', !isActive);
         btn.classList.toggle('border-transparent', !isActive);
     });
-    const clientPanel = document.getElementById('client-panel');
     if (fileTree) fileTree.classList.toggle('hidden', tab !== 'files');
     if (tasksPanel) tasksPanel.classList.toggle('hidden', tab !== 'tasks');
     if (jobsPanel) jobsPanel.classList.toggle('hidden', tab !== 'jobs');
-    if (clientPanel) clientPanel.classList.toggle('hidden', tab !== 'client');
     _tasksTabActive = tab === 'tasks';
     _jobsTabActive = tab === 'jobs';
     if (_tasksTabActive) { loadTasks(); if (!_tasksInterval) _tasksInterval = setInterval(loadTasks, 5000); }
     else { if (_tasksInterval) { clearInterval(_tasksInterval); _tasksInterval = null; } }
     if (_jobsTabActive) { loadJobs(); if (!_jobsInterval) _jobsInterval = setInterval(loadJobs, 10000); }
     else { if (_jobsInterval) { clearInterval(_jobsInterval); _jobsInterval = null; } }
-    if (tab === 'client') loadClientInfo();
 }
 
-async function loadClientInfo() {
-    const panel = document.getElementById('client-panel');
-    if (!panel) return;
-    panel.innerHTML = '<span class="text-slate-500">Loading...</span>';
+function openClientModal() {
+    const modal = document.getElementById('client-modal');
+    if (!modal) return;
+    modal.classList.remove('hidden');
+    modal.classList.add('flex');
+    _renderClientModal();
+}
+function closeClientModal() {
+    const modal = document.getElementById('client-modal');
+    if (!modal) return;
+    modal.classList.add('hidden');
+    modal.classList.remove('flex');
+}
+async function _renderClientModal() {
+    const body = document.getElementById('client-modal-body');
+    if (!body) return;
+    body.innerHTML = '<span class="text-slate-500">Loading...</span>';
     try {
         const data = await api('/api/models');
         const models = data.models || [];
         const connected = data.proxy_connected;
         const currency = document.body.dataset.currency || '$';
-        let html = `<div class="space-y-3">`;
-        html += `<div class="flex items-center gap-2 mb-2">
-            <span class="text-sm font-bold text-white">Client Info</span>
+        let html = `<div class="flex items-center justify-between mb-3">
             <span class="text-xs ${connected ? 'text-emerald-400' : 'text-red-400'}">${connected ? '🟢 Proxy connected' : '🔴 Proxy offline'}</span>
+            <button onclick="_retryProxy()" class="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors">Retry</button>
         </div>`;
         if (!models.length) {
-            html += `<div class="text-slate-500 italic">No models available</div>`;
+            html += `<div class="text-slate-500 italic py-4 text-center">No models available.<br>Models will appear after proxy connects.</div>`;
         } else {
-            html += `<div class="text-xs text-slate-500 mb-1">${models.length} models available</div>`;
+            html += `<div class="text-xs text-slate-500 mb-2">${models.length} models</div>`;
             for (const m of models) {
-                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k ctx` : '';
-                const price = (m.price_input != null && m.price_output != null)
-                    ? `${currency}${m.price_input}/M in · ${currency}${m.price_output}/M out`
-                    : '';
-                html += `<div class="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
-                    <div class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</div>
-                    <div class="text-[10px] text-slate-500 font-mono">${escHtml(m.id)}</div>
-                    <div class="text-[10px] text-slate-400 mt-0.5">${[ctx, price].filter(Boolean).join(' · ')}</div>
+                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k` : '';
+                const priceIn = m.price_input != null ? `${currency}${m.price_input}/M` : '';
+                const priceOut = m.price_output != null ? `${currency}${m.price_output}/M` : '';
+                html += `<div class="p-2.5 bg-slate-800/60 rounded-xl border border-slate-700/40 mb-2">
+                    <div class="flex items-center justify-between">
+                        <span class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</span>
### cde3ca0cd #92: backend 403 block on proxy/profiles/tunnel API for enterprise

diff --git a/app/routes/system.py b/app/routes/system.py
index 4c488230d..6c1e91ebf 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -10,11 +10,11 @@ import os
 import re
 import time
 from pathlib import Path
 from typing import Optional
 
-from fastapi import APIRouter, Request, Form
+from fastapi import APIRouter, HTTPException, Request, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
 from pydantic import BaseModel
 
 from app.auth import is_auth_enabled
 from app.db import get_all_sessions, list_profiles, upsert_profile, delete_profile
@@ -294,23 +294,20 @@ async def get_pipelines():
 
 
 @router.get("/api/profiles")
 async def get_profiles():
     """Все профили Claude: ``[{name, config_dir}]``."""
+    if is_auth_enabled():
+        raise HTTPException(403, "Not available")
     return list_profiles()
 
 
 @router.post("/api/profiles")
 async def create_profile(req: ProfileRequest):
-    """Создать или обновить профиль. Имя валидируется тем же regex, что у сессий.
-
-    Валидация ``config_dir`` — **мягкая**: если путь непустой и не указывает на
-    существующую директорию, профиль всё равно сохраняется, но в ответ
-    добавляется ``warning``. Это не блокирует пользователя (папку может создать
-    CLI или она появится позже), но предупреждает об опечатке заранее, а не
-    при первом запуске агента. Формат ответа: ``{profiles, warning}``.
-    """
+    """Создать или обновить профиль."""
+    if is_auth_enabled():
+        raise HTTPException(403, "Not available")
     if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", req.name):
         return JSONResponse(
             {"error": "name must be alphanumeric with ._- allowed, 1-50 chars"},
             status_code=400,
         )
@@ -325,11 +322,13 @@ async def create_profile(req: ProfileRequest):
     return {"profiles": list_profiles(), "warning": warning}
 
 
 @router.delete("/api/profiles/{name}")
 async def remove_profile(name: str):
-    """Удалить профиль. Сид-профиль ``personal`` защищён → 409."""
+    """Удалить профиль."""
+    if is_auth_enabled():
+        raise HTTPException(403, "Not available")
     try:
         delete_profile(name)
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=409)
     return list_profiles()
### a1c89c427 #88: restore auto-bootstrap (lost in revert)

diff --git a/app/main.py b/app/main.py
index b7de25ff4..4ec6a4952 100644
--- a/app/main.py
+++ b/app/main.py
@@ -26,10 +26,12 @@ async def lifespan(app: FastAPI):
     # YouGile sync fired from to_thread workers needs the app loop captured
     from app import tm as _tm_mod
     _tm_mod.set_main_loop(asyncio.get_running_loop())
     from app import tm_yougile  # noqa: F401 — registers tm sync hooks (on_task_synced, on_payment_changed)
     await manager.auto_resume_all()
+    from app.bootstrap import ensure_bootstrap
+    await ensure_bootstrap()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
### 2364a9e25 #91: fix proxy URL — read ANTHROPIC_BASE_URL (set in container .env)

diff --git a/app/models.py b/app/models.py
index a4801b9af..b9f98ddf7 100644
--- a/app/models.py
+++ b/app/models.py
@@ -114,11 +114,11 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
 
     enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
     enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
     """
     global _proxy_connected
-    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    base_url = os.environ.get("ANTHROPIC_BASE_URL", os.environ.get("UPSTREAM_API", "https://api.anthropic.com"))
     api_key = os.environ.get("ANTHROPIC_API_KEY", "")
     url = f"{base_url.rstrip('/')}/v1/models"
 
     proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
 
### 200d6c33c #91: semantic aliases for dynamic models (opus/sonnet/deepseek) + resolve warning

diff --git a/app/models.py b/app/models.py
index b9f98ddf7..9ad00d583 100644
--- a/app/models.py
+++ b/app/models.py
@@ -191,16 +191,47 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
 
         for alias in _generate_aliases(mid):
             if alias not in ALIASES and alias != mid:
                 ALIASES[alias] = mid
 
+    _generate_semantic_aliases()
     _proxy_connected = True
     mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
     logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
     return True
 
 
+# Semantic alias patterns: short name → match first model containing substring
+_SEMANTIC_PATTERNS = [
+    ("opus", "opus"),
+    ("opus4.8", "opus-4-8"),
+    ("opus4.6", "opus-4-6"),
+    ("sonnet", "sonnet"),
+    ("haiku", "haiku"),
+    ("fable", "fable"),
+    ("deepseek", "deepseek"),
+    ("deepseek-flash", "deepseek-v4-flash"),
+    ("deepseek-pro", "deepseek-v4-pro"),
+    ("gemini", "gemini"),
+    ("gemini-flash", "gemini-2.5-flash"),
+    ("llama", "llama"),
+    ("mistral", "mistral"),
+    ("gpt-mini", "gpt-4o-mini"),
+]
+
+
+def _generate_semantic_aliases():
+    """Generate standard short aliases (opus, sonnet, etc.) from loaded models."""
+    for alias, pattern in _SEMANTIC_PATTERNS:
+        if alias in ALIASES:
+            continue
+        for mid in MODELS:
+            if pattern in mid:
+                ALIASES[alias] = mid
+                break
+
+
 async def refresh_models() -> None:
     """Startup helper — fetch models, enterprise-aware."""
     from app.auth import is_auth_enabled
     enterprise = is_auth_enabled()
     ok = await fetch_models_from_proxy(enterprise_mode=enterprise)
@@ -217,10 +248,12 @@ def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
     if m in MODELS:
         return m
+    if MODELS:
+        logger.warning(f"resolve_model: '{model}' not found in {len(MODELS)} loaded models, returning as-is")
     return model
 
 
 def backend_for_model(model: str) -> str:
     return BACKENDS.get(model, "claude")