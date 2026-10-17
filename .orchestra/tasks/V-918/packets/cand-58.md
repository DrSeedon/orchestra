# Candidate cand-58

## ORIGIN commit 4d3b26cc87 (2026-06-12): feat: toggle TG topic for agents via context menu
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 4b1358612..e4c7a41fa 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -691,16 +691,27 @@ async def update_progress(name: str, req: dict):
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
     session.progress_pct = pct
     session.progress_status = status_text
     session._persist()
     return {"ok": True}
 
 
+@router.patch("/api/sessions/{name}/tg-topic")
+async def toggle_tg_topic(name: str, scope: str, enabled: bool):
+    from app.db import save_session
+    found = manager.get_by_name(name, scope)
+    if not found:
+        return JSONResponse({"error": "not found"}, status_code=404)
+    found.tg_topic = enabled
+    save_session(found.to_dict())
+    return {"ok": True, "name": name, "tg_topic": enabled}
+
+
 @router.get("/api/sessions/{name}/inbox")
 async def get_session_inbox(name: str, scope: str):
     from app.db import get_inbox, ack_inbox
     session_id = manager.get_session_id(name, scope)
     if not session_id:
         return JSONResponse({"error": "not found"}, status_code=404)
     messages = get_inbox(session_id)
     for m in messages:
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 80fdf232b..03b9150fb 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1424,20 +1424,62 @@ function createAgentItem(s) {
             const ptext = document.createElement('div');
             ptext.style.cssText = 'font-size:9px;color:#64748b;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
             ptext.textContent = `${ppct}% — ${s.progress_status}`;
             info.appendChild(ptext);
         }
     }
     item.append(icon, info);
 
+    item.addEventListener('contextmenu', (e) => {
+        e.preventDefault();
+        _showAgentContextMenu(e, s);
+    });
+
     if (isSelected) updateAgentInfo(s);
     return item;
 }
 
+let _agentCtxMenu = null;
+function _showAgentContextMenu(e, s) {
+    if (_agentCtxMenu) _agentCtxMenu.remove();
+    const menu = document.createElement('div');
+    _agentCtxMenu = menu;
+    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
+    const close = () => { if (_agentCtxMenu) { _agentCtxMenu.remove(); _agentCtxMenu = null; } };
+    document.addEventListener('click', close, { once: true });
+
+    const mkItem = (label, color, fn) => {
+        const item = document.createElement('div');
+        item.style.cssText = `padding:6px 14px;font-size:12px;color:${color};cursor:pointer;white-space:nowrap`;
+        item.textContent = label;
+        item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
+        item.addEventListener('mouseleave', () => item.style.background = '');
+        item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
+        return item;
+    };
+
+    const tgEnabled = s.tg_topic;
+    menu.appendChild(mkItem(
+        tgEnabled ? '📌 TG Topic: ON → OFF' : '📌 TG Topic: OFF → ON',
+        tgEnabled ? '#f59e0b' : '#94a3b8',
+        async () => {
+            try {
+                await api(`/api/sessions/${s.name}/tg-topic?scope=${encodeURIComponent(currentScope)}&enabled=${!tgEnabled}`, { method: 'PATCH' });
+                await refreshSessions();
+            } catch (e) { console.error('TG topic toggle failed:', e); }
+        }
+    ));
+
+    document.body.appendChild(menu);
+    const rect = menu.getBoundingClientRect();
+    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
+    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
+}
+
 // === Chat ===
 // Optimistic UI: show message immediately, debounce actual send so rapid
 // follow-up messages get batched. The server echoes back via SSE which
 // replaces the bubble with the canonical version.
 async function sendChat() {
     const input = $('#chat-input');
     const msg = input.value.trim();
     if (!msg || !currentScope || !selectedAgent) return;


## LATER FIX 86bb4e238a (117.3 days later): V-753: #V-753: fix dashboard TG topic toggle persistence
lines of origin it changed/deleted: 10
(code only, capped 400 lines)

V-753: #V-753: fix dashboard TG topic toggle persistence

Squashed commits:
- #V-753: fix dashboard TG topic toggle persistence
- #V-753: clarify report branch
- #V-753: guard TG topic API source in merge gate
- #V-753: execute TG topic menu in Node guard
- #V-753: report API and route mutation together
- #V-753: record merge gate source mutation

Orchestra-Operation: c8df6582-fe43-4c17-988a-18ad0c8be916


diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 7850dc053..b6f0324fd 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -3518,19 +3518,8 @@ async def update_progress(name: str, req: dict):
         # progress is live-only: detached sessions 404 (write would flip legacy 404→200)
         session = next((s for s in manager.sessions.values() if s.name == name), None)
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
     session.progress_pct = pct
     session.progress_status = status_text
     session._persist()
     return {"ok": True}
-
-
-@router.patch("/api/sessions/{name}/tg-topic")
-async def toggle_tg_topic(name: str, scope: str, enabled: bool):
-    from app.db import save_session
-    found = manager.get_by_name(name, scope)
-    if not found:
-        return JSONResponse({"error": "not found"}, status_code=404)
-    found.tg_topic = enabled
-    save_session(found.to_dict())
-    return {"ok": True, "name": name, "tg_topic": enabled}
diff --git a/app/static/js/app.js b/app/static/js/app.js
index a71e9ba76..60da5afe7 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -3267,17 +3267,20 @@ function _showAgentContextMenu(e, s) {
     };
 
     const tgEnabled = s.tg_topic;
     menu.appendChild(mkItem(
         tgEnabled ? '📌 TG Topic: ON → OFF' : '📌 TG Topic: OFF → ON',
         tgEnabled ? '#f59e0b' : '#94a3b8',
         async () => {
             try {
-                await api(`/api/sessions/${s.name}/tg-topic?scope=${encodeURIComponent(currentScope)}&enabled=${!tgEnabled}`, { method: 'PATCH' });
+                await api(`/api/sessions/${s.name}/tg_topic`, {
+                    method: 'POST',
+                    body: JSON.stringify({ scope: currentScope, enabled: !tgEnabled }),
+                });
                 await refreshSessions();
             } catch (e) { console.error('TG topic toggle failed:', e); }
         }
     ));
 
     document.body.appendChild(menu);
     const rect = menu.getBoundingClientRect();
     if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
diff --git a/tests/route_surface_snapshot.json b/tests/route_surface_snapshot.json
index d0b94402c..7b4fb88f0 100644
--- a/tests/route_surface_snapshot.json
+++ b/tests/route_surface_snapshot.json
@@ -457,22 +457,16 @@
   ]
  ],
  [
   "/api/sessions/{name}/switch-branch",
   [
    "POST"
   ]
  ],
- [
-  "/api/sessions/{name}/tg-topic",
-  [
-   "PATCH"
-  ]
- ],
  [
   "/api/sessions/{name}/tg_topic",
   [
    "POST"
   ]
  ],
  [
   "/api/sessions/{name}/wip",
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index c6c6133c0..21335e449 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -4,16 +4,17 @@ The dashboard is started in-process by ``dashboard_browser`` (isolated DB,
 no auth). A missing :8888 must not skip these tests — that printed green
 while 12 checks never ran (#145, #242).
 """
 
 import base64
 import json
 import os
 import re
+import shutil
 import socket
 import subprocess
 import tempfile
 import sys
 import time
 import urllib.error
 import urllib.request
 from urllib.parse import parse_qs, quote, urlsplit
@@ -463,16 +464,134 @@ def test_dashboard_loads(dashboard_page: Page):
     expect(dashboard_page).to_have_title("🎼 Orchestra")
 
 
 def test_sidebar_agents_visible(dashboard_page: Page):
     agent_list = dashboard_page.locator("#agent-list")
     expect(agent_list).to_be_visible()
 
 
+def test_tg_topic_context_menu_persists_through_frontend_api(dashboard_browser: Browser):
+    page = dashboard_browser.new_page()
+    try:
+        _route_frontend_sources(page)
+        _goto_dashboard(page)
+        page.wait_for_function("() => typeof _showAgentContextMenu === 'function'")
+        page.evaluate("currentScope = '/tmp/fe-scope'")
+
+        for enabled, label in ((True, "OFF → ON"), (False, "ON → OFF")):
+            page.evaluate("""enabled => _showAgentContextMenu(
+                {clientX: 20, clientY: 20},
+                {name: 'notify-268-probe', tg_topic: enabled},
+            )""", not enabled)
+            with page.expect_response(lambda response: (
+                response.request.method == "POST"
+                and response.url.endswith("/api/sessions/notify-268-probe/tg_topic")
+            )) as response_info:
+                page.get_by_text(f"📌 TG Topic: {label}", exact=True).click()
+
+            response = response_info.value
+            assert response.status == 200
+            assert response.json()["tg_topic"] is enabled
+
+            reloaded = page.request.get(
+                f"{_dashboard_base()}/api/sessions?scope=%2Ftmp%2Ffe-scope"
+            )
+            assert reloaded.status == 200
+            worker = next(
+                session for session in reloaded.json()
+                if session["name"] == "notify-268-probe"
+            )
+            assert bool(worker["tg_topic"]) is enabled
+    finally:
+        page.close()
+
+
+def test_tg_topic_frontend_and_route_share_the_persistent_api_contract():
+    import ast
+
+    root = Path(__file__).resolve().parent.parent
+    frontend = (root / "app/static/js/app.js").read_text()
+    start = frontend.index("function _showAgentContextMenu")
+    end = frontend.index("\nconst FILE_ICONS", start)
+    menu_function = frontend[start:end]
+    node = shutil.which("node")
+    assert node, "Node.js is required to exercise the dashboard TG topic action"
+    script = r"""
+global.window = {innerWidth: 1000, innerHeight: 800};
+let currentScope = '/test/scope';
+let _agentCtxMenu = null;
+let request = null;
+let refreshCount = 0;
+const element = () => ({
+    style: {}, children: [],
+    addEventListener(name, fn) { this['on_' + name] = fn; },
+    appendChild(child) { this.children.push(child); },
+    getBoundingClientRect() { return {right: 10, bottom: 10, width: 10, height: 10}; },
+    remove() {},
+});
+global.document = {
+    createElement: element,
+    addEventListener() {},
+    body: {appendChild(menu) { global.menu = menu; }},
+};
+global.api = async (url, opts) => { request = {url, opts}; return {}; };
+global.refreshSessions = async () => { refreshCount += 1; };
+""" + menu_function + r"""
+(async () => {
+    _showAgentContextMenu({clientX: 0, clientY: 0}, {name: 'worker', tg_topic: false});
+    menu.children[0].on_click({stopPropagation() {}});
+    await new Promise(resolve => setTimeout(resolve, 0));
+    console.log(JSON.stringify({
+        url: request.url,
+        method: request.opts.method,
+        body: request.opts.body ? JSON.parse(request.opts.body) : null,
+        refreshCount,
+    }));
+})();
+"""
+    result = subprocess.run(
+        [node, "-e", script], capture_output=True, text=True, timeout=10, check=True,
+    )
+    frontend_request = json.loads(result.stdout)
+    frontend_ok = frontend_request == {
+        "url": "/api/sessions/worker/tg_topic",
+        "method": "POST",
+        "body": {"scope": "/test/scope", "enabled": True},
+        "refreshCount": 1,
+    }
+
+    routes = ast.parse((root / "app/routes/sessions.py").read_text())
+    declared = set()
+    for node in ast.walk(routes):
+        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
+            continue
+        for decorator in node.decorator_list:
+            if not isinstance(decorator, ast.Call):
+                continue
+            target = decorator.func
+            if (
+                isinstance(target, ast.Attribute)
+                and isinstance(target.value, ast.Name)
+                and target.value.id == "router"
+                and target.attr in {"post", "patch"}
+                and decorator.args
+                and isinstance(decorator.args[0], ast.Constant)
+            ):
+                declared.add((target.attr, decorator.args[0].value))
+
+    route_ok = (
+        ("post", "/api/sessions/{name}/tg_topic") in declared
+        and ("patch", "/api/sessions/{name}/tg-topic") not in declared
+    )
+    assert frontend_ok and route_ok, (
+        f"frontend request={frontend_request}; route contract valid={route_ok}"
+    )
+
+
 def test_live_stream_status_updates_selected_agent_badge(dashboard_page: Page):
     dashboard_page.wait_for_function("() => typeof _applyLiveAgentStatus === 'function'")
     dashboard_page.wait_for_selector('.agent-item[data-agent-name="notify-268-probe"]')
     dashboard_page.evaluate("""() => {
         window.__savedRenderAgentList403 = renderAgentList;
         renderAgentList = () => {};
     }""")
     try: