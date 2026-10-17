# Candidate cand-63

## ORIGIN commit 95abdc8576 (2026-07-26): fix: unread tabs track orchestrator turns
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 96d4d636c..b72480fa3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -798,16 +798,32 @@ function _orchState(o) {
 
 function _paintStatusDot(dot, o) {
     const state = _orchState(o);
     dot.textContent = _STATUS_ICON[state];
     dot.style.backgroundColor = _STATUS_BG[state];
     dot.title = _STATUS_TITLE[state];
 }
 
+function _orchestratorTurnFinished(previous, current) {
+    return previous.status === 'running' && current.status !== 'running';
+}
+
+function _syncUnreadDot(tab, scope) {
+    const existing = tab.querySelector('.tab-unread');
+    if (_unreadTabs.has(scope) && !existing) {
+        const unread = document.createElement('span');
+        unread.className = 'tab-unread';
+        unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
+        tab.appendChild(unread);
+    } else if (!_unreadTabs.has(scope) && existing) {
+        existing.remove();
+    }
+}
+
 function renderOrchTabs(sorted) {
     const tabs = $('#orch-tabs');
     tabs.innerHTML = '';
     const ordered = _applyTabOrder(sorted);
     const hidden = _getHiddenTabs();
     let dragTab = null;
     _updateHiddenBtn();
     for (const o of ordered) {
@@ -830,22 +846,17 @@ function renderOrchTabs(sorted) {
             orchPill.style.marginLeft = '3px';
             orchPill.style.verticalAlign = 'middle';
             orchPill.dataset.hideCold = '1';
             if (orchPill.dataset.tier === 'cold') orchPill.style.display = 'none';
             tab.appendChild(orchPill);
         }
         tab.title = o.scope;
         tab.style.position = 'relative';
-        if (_unreadTabs.has(o.scope)) {
-            const unread = document.createElement('span');
-            unread.className = 'tab-unread';
-            unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
-            tab.appendChild(unread);
-        }
+        _syncUnreadDot(tab, o.scope);
         tab.addEventListener('click', () => selectOrchestrator(o.name, o.scope));
         tab.addEventListener('dragstart', (e) => {
             dragTab = tab;
             tab.style.opacity = '0.4';
             e.dataTransfer.effectAllowed = 'move';
         });
         tab.addEventListener('dragend', () => {
             tab.style.opacity = '';
@@ -1112,25 +1123,17 @@ function initHiddenTabsBtn() {
 function updateOrchTabDots() {
     const tabs = document.querySelectorAll('#orch-tabs .orch-tab');
     tabs.forEach(tab => {
         const scope = tab.title;
         const o = orchData.find(x => x.scope === scope);
         if (!o) return;
         const dot = tab.querySelector('.tab-dot');
         if (dot) _paintStatusDot(dot, o);
-        const existing = tab.querySelector('.tab-unread');
-        if (_unreadTabs.has(scope) && !existing) {
-            const unread = document.createElement('span');
-            unread.className = 'tab-unread';
-            unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
-            tab.appendChild(unread);
-        } else if (!_unreadTabs.has(scope) && existing) {
-            existing.remove();
-        }
+        _syncUnreadDot(tab, scope);
     });
 }
 
 function selectOrchestrator(name, scope) {
     _unreadTabs.delete(scope);
     const picker = $('#orch-picker');
     picker.value = scope;
     const opt = [...picker.options].find(o => o.dataset.name === name);
@@ -4923,19 +4926,17 @@ async function refreshSessions() {
         $('#stats-line').innerHTML = `${stats.active} active · ${stats.total_sessions} total<br><span style="color:#64748b;font-size:10px">${MODEL_COST_CURRENCY}${stats.total_cost_usd} (w/o cache)</span>`;
         renderAgentList(sessions);
 
         try {
             const freshOrchs = await api('/api/orchestrators', { signal });
             for (const fo of freshOrchs) {
                 const existing = orchData.find(o => o.name === fo.name);
                 if (existing) {
-                    const wasRunning = existing.status === 'running' || existing.any_running;
-                    const nowIdle = fo.status !== 'running' && !fo.any_running;
-                    if (wasRunning && nowIdle && fo.scope !== currentScope) {
+                    if (_orchestratorTurnFinished(existing, fo) && fo.scope !== currentScope) {
                         _unreadTabs.add(fo.scope);
                     }
                     existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running;
                 }
             }
             updateOrchTabDots();
         } catch {}
 
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index d74e56f1e..6727cf5e2 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -103,16 +103,66 @@ def test_usage_bar_visible(dashboard_page: Page):
     expect(usage_bar).to_be_attached()
 
 
 def test_header_has_orch_tabs(dashboard_page: Page):
     tabs = dashboard_page.locator("#orch-tabs")
     expect(tabs).to_be_visible()
 
 
+def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    assert source.count("_unreadTabs.add(") == 1
+    assert source.count("className = 'tab-unread'") == 1
+    assert "_orchestratorTurnFinished(existing, fo)" in source
+
+    def function_source(name):
+        marker = f"function {name}"
+        return marker + source.split(marker, 1)[1].split("\n}\n", 1)[0] + "\n}"
+
+    page = dashboard_browser.new_page()
+    page.set_content("<div id='tab'></div>")
+    page.add_script_tag(content="\n".join([
+        "const _unreadTabs = new Set();",
+        function_source("_orchestratorTurnFinished"),
+        function_source("_syncUnreadDot"),
+    ]))
+
+    result = page.evaluate("""() => {
+        const workerFinished = _orchestratorTurnFinished(
+            {status: 'idle', any_running: true},
+            {status: 'idle', any_running: false},
+        );
+        const orchestratorFinished = _orchestratorTurnFinished(
+            {status: 'running', any_running: true},
+            {status: 'idle', any_running: true},
+        );
+        const tab = document.getElementById('tab');
+        _syncUnreadDot(tab, '/foreign');
+        const before = tab.querySelectorAll('.tab-unread').length;
+        _unreadTabs.add('/foreign');
+        _syncUnreadDot(tab, '/foreign');
+        _syncUnreadDot(tab, '/foreign');
+        const afterAdd = tab.querySelectorAll('.tab-unread').length;
+        _unreadTabs.delete('/foreign');
+        _syncUnreadDot(tab, '/foreign');
+        const afterDelete = tab.querySelectorAll('.tab-unread').length;
+        return {workerFinished, orchestratorFinished, before, afterAdd, afterDelete};
+    }""")
+    page.close()
+
+    assert result == {
+        "workerFinished": False,
+        "orchestratorFinished": True,
+        "before": 0,
+        "afterAdd": 1,
+        "afterDelete": 0,
+    }
+
+
 def test_left_panel_has_tabs(dashboard_page: Page):
     files_tab = dashboard_page.locator('[data-left-tab="files"]')
     tasks_tab = dashboard_page.locator('[data-left-tab="tasks"]')
     jobs_tab = dashboard_page.locator('[data-left-tab="jobs"]')
     expect(files_tab).to_be_visible()
     expect(tasks_tab).to_be_visible()
     expect(jobs_tab).to_be_visible()
 


## LATER FIX 59cf84d21a (81.0 days later): V-863: #V-863: restore unread dots on orchestrator tabs
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

V-863: #V-863: restore unread dots on orchestrator tabs

Orchestra-Operation: 4f832212-b645-479c-a96d-cd5125737940


diff --git a/app/static/js/app.js b/app/static/js/app.js
index 2a3556a74..1ca5a82a3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1871,19 +1871,33 @@ async function restartServer() {
     // перезагружалась в мёртвый сервер и юзер получал 502 от nginx вместо дашборда.
     // Возврат ловит heartbeat и восстанавливает состояние на месте.
 }
 
 // === Orchestrator Picker ===
 let orchData = [];
 const _unreadTabs = new Set();
 
+// A foreign tab turns red when its orchestrator finished a turn since the last list we
+// saw: status left 'running', or last_turn_ts moved (a turn shorter than the poll gap).
+function _markUnreadTurns(previous, current) {
+    for (const fresh of current) {
+        const old = previous.find(o => o.name === fresh.name && o.scope === fresh.scope);
+        if (!old || fresh.scope === currentScope) continue;
+        const newTurn = fresh.last_turn_ts && fresh.last_turn_ts !== old.last_turn_ts;
+        if (_orchestratorTurnFinished(old, fresh) || newTurn) _unreadTabs.add(fresh.scope);
+    }
+}
+
 function _renderOrchestrators(allOrchs) {
     // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
-    orchData = allOrchs.filter(o => !o.parent_name);
+    const fresh = allOrchs.filter(o => !o.parent_name);
+    // The 60 s poll replaces orchData wholesale; compare first, or the transition is lost.
+    _markUnreadTurns(orchData, fresh);
+    orchData = fresh;
     const picker = $('#orch-picker');
     picker.innerHTML = '';
     for (const o of orchData) {
         const opt = document.createElement('option');
         opt.value = o.scope;
         opt.dataset.id = o.id;
         opt.dataset.name = o.name;
         opt.textContent = o.name;
@@ -3547,23 +3561,22 @@ async function refreshSessions() {
         Connection.clear('sessions');
 
         // Список оркестраторов нужен для меток непрочитанного по ЧУЖИМ вкладкам, но он
         // весит 55 КБ и раньше тянулся каждые 3 с вместе с сессиями — 1.1 МБ в минуту на
         // канале 15–80 КБ/с. Метка, опоздавшая на десяток секунд, никому не мешает.
         if (Date.now() - _orchFreshAt >= _ORCH_REFRESH_MS) try {
             _orchFreshAt = Date.now();
             const freshOrchs = await api('/api/orchestrators', { signal });
+            _markUnreadTurns(orchData, freshOrchs);
             for (const fo of freshOrchs) {
                 const existing = orchData.find(o => o.name === fo.name);
                 if (existing) {
-                    if (_orchestratorTurnFinished(existing, fo) && fo.scope !== currentScope) {
-                        _unreadTabs.add(fo.scope);
-                    }
                     existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running;
+                    existing.last_turn_ts = fo.last_turn_ts;
                 }
             }
             updateOrchTabDots();
         } catch (e) {
             // Метки непрочитанного — украшение, но их пропажа не должна быть немой:
             // юзер иначе решит, что чужие вкладки молчат, а они просто не доехали.
             console.warn(`orchestrator dots: ${e.name}: ${e.message}`);
         }
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 5d69b73b1..4f38a77ad 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1103,22 +1103,57 @@ def test_hidden_orchestrator_list_reuses_tab_status_and_cache(dashboard_browser:
     assert result["before"]["running-orchestrator"]["status"] == "⚡"
     assert result["before"]["waiting-orchestrator"]["status"] == "📆"
     assert result["before"]["idle-orchestrator"]["status"] == "☕️"
     assert "🔥" in result["before"]["idle-orchestrator"]["cache"]
     assert result["afterLiveUpdate"]["status"] == "⚡"
     assert result["afterLiveUpdate"]["cache"] == "🔥"
 
 
-def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
+def test_unread_dot_survives_orchestrator_list_poll(dashboard_browser: Browser):
+    """V-863: the 60 s list poll replaces orchData; the dot must still appear and clear."""
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
-    assert source.count("_unreadTabs.add(") == 1
-    assert source.count("className = 'tab-unread'") == 1
-    assert "_orchestratorTurnFinished(existing, fo)" in source
 
+    def function_source(name):
+        marker = f"function {name}"
+        return marker + source.split(marker, 1)[1].split("\n}\n", 1)[0] + "\n}"
+
+    page = dashboard_browser.new_page()
+    page.set_content("<div id='tab'></div>")
+    page.add_script_tag(content="\n".join([
+        "const _unreadTabs = new Set(); let orchData = []; let currentScope = '/mine';",
+        "let selectedAgent = null; const $ = s => document.querySelector(s);",
+        function_source("_orchestratorTurnFinished"),
+        function_source("_markUnreadTurns"),
+        function_source("_syncUnreadDot"),
+        # the real _renderOrchestrators minus DOM picker work: only the compare-then-replace order matters
+        "function _poll(list) { const fresh = list.filter(o => !o.parent_name);"
+        " _markUnreadTurns(orchData, fresh); orchData = fresh; }",
+    ]))
+    result = page.evaluate("""() => {
+        const o = (scope, status, ts) => ({name: scope.slice(1), scope, status, last_turn_ts: ts});
+        const tab = document.getElementById('tab');
+        const dot = scope => { _syncUnreadDot(tab, scope); return tab.querySelectorAll('.tab-unread').length; };
+        _poll([o('/mine', 'idle', 't0'), o('/other', 'running', 't0'), o('/quick', 'idle', 't0')]);
+        const quiet = dot('/other');
+        _poll([o('/mine', 'idle', 't1'), o('/other', 'idle', 't1'), o('/quick', 'idle', 't1')]);
+        const finishedOther = _unreadTabs.has('/other');
+        const shortTurn = _unreadTabs.has('/quick');
+        const ownTab = _unreadTabs.has('/mine');
+        const shown = dot('/other');
+        _unreadTabs.delete('/other');
+        return {quiet, finishedOther, shortTurn, ownTab, shown, cleared: dot('/other')};
+    }""")
+    page.close()
+    assert result == {"quiet": 0, "finishedOther": True, "shortTurn": True,
+                      "ownTab": False, "shown": 1, "cleared": 0}
+
+
+def test_orchestrator_unread_tracks_own_turn_only(dashboard_browser: Browser):
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     def function_source(name):
         marker = f"function {name}"
         return marker + source.split(marker, 1)[1].split("\n}\n", 1)[0] + "\n}"
 
     page = dashboard_browser.new_page()
     page.set_content("<div id='tab'></div>")
     page.add_script_tag(content="\n".join([
         "const _unreadTabs = new Set();",