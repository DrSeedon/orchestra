# Context for item-02

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index f6faa784c..e025c6fff 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1790,58 +1790,52 @@ const _unreadTabs = new Set();
 
 function _renderOrchestrators(allOrchs) {
     // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
     orchData = allOrchs.filter(o => !o.parent_name);
     const picker = $('#orch-picker');
     picker.innerHTML = '';
     for (const o of orchData) {
         const opt = document.createElement('option');
         opt.value = o.scope;
         opt.dataset.id = o.id;
         opt.dataset.name = o.name;
         opt.textContent = o.name;
         picker.appendChild(opt);
     }
 
     const lastScope = localStorage.getItem('lastOrchScope');
     const lastName = localStorage.getItem('lastOrchName');
     const recentRaw = localStorage.getItem('recentOrchs');
     const recent = recentRaw ? JSON.parse(recentRaw) : [];
 
-    const sorted = [...orchData].sort((a, b) => {
-        const ai = recent.indexOf(a.name);
-        const bi = recent.indexOf(b.name);
-        if (ai >= 0 && bi >= 0) return ai - bi;
-        if (ai >= 0) return -1;
-        if (bi >= 0) return 1;
-        return 0;
-    });
-
-    renderOrchTabs(sorted);
+    // Порядок вкладок принадлежит ТОЛЬКО пользователю (`tabOrder`, перетаскивание внутри
+    // renderOrchTabs). Раньше список сначала сортировался по недавно открытым, и вкладки
+    // переставлялись сами: каждый клик менял `recentOrchs`, а после перезагрузки порядок
+    // оказывался другим. Список сервера берём как есть; `recent` остаётся только памятью
+    // о том, кого открыть по умолчанию.
+    renderOrchTabs(orchData);
 
     if (orchData.length > 0 && !currentScope) {
-        const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
-        if (match) {
-            selectOrchestrator(match.name, match.scope);
-        } else {
-            selectOrchestrator(sorted[0].name, sorted[0].scope);
-        }
+        const match = orchData.find(o => o.scope === lastScope && o.name === lastName)
+            || recent.map(name => orchData.find(o => o.name === name)).find(Boolean)
+            || orchData[0];
+        selectOrchestrator(match.name, match.scope);
     }
 }
 
 async function _loadOrchestratorsNow() {
     try {
         const allOrchs = await api('/api/orchestrators', {
             pollKey: 'orchestrators',
             priority: 'critical',
         });
         // Данные только что получены. Без этой отметки дроссель в refreshSessions считает
         // их протухшими и через полсекунды тянет тот же список второй раз (#71).
         _orchFreshAt = Date.now();
         _renderOrchestrators(allOrchs);
         snapshotSave('orchestrators', allOrchs);
         Connection.clear('orchestrators');
     } catch (e) {
         // Пустые вкладки без причины — это то, на что юзер и жалуется. Молчать нельзя:
         // без вкладок дашборд не выбирает scope, и не работает ВООБЩЕ ничего.
         console.warn(`orchestrators: ${e.name}: ${e.message}`);
         const snapshot = orchData.length ? null : snapshotLoad('orchestrators');
@@ -2315,41 +2309,42 @@ function initHiddenTabsBtn() {
 }
 
 function updateOrchTabDots() {
     const tabs = document.querySelectorAll('#orch-tabs .orch-tab');
     tabs.forEach(tab => {
         const scope = tab.title;
         const o = orchData.find(x => x.scope === scope);
         if (!o) return;
         const dot = tab.querySelector('.tab-dot');
         if (dot) _paintStatusDot(dot, o);
         _syncUnreadDot(tab, scope);
     });
 }
 
 function selectOrchestrator(name, scope) {
     const picker = $('#orch-picker');
     picker.value = scope;
     const opt = [...picker.options].find(o => o.dataset.name === name);
     if (opt) picker.selectedIndex = opt.index;
 
-    // Keep last 10 recently used orchestrators — used to sort tabs on next load
+    // Последние 10 открытых: нужны, только чтобы выбрать, кого открыть при следующем
+    // запуске без сохранённого выбора. Порядок вкладок отсюда НЕ берётся.
     const recent = JSON.parse(localStorage.getItem('recentOrchs') || '[]');
     const filtered = recent.filter(n => n !== name);
     filtered.unshift(name);
     localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));
 
     onOrchestratorChange();
     renderOrchTabs(orchData);
 }
 
 // Отрисовать готовые строки журнала и выставить отметки, от которых пляшет connectSSE.
 // Отличает проигрывание истории от живой строки: часть отрисовки имеет побочные эффекты
 // (обновить панель задач), и в прошлом они не нужны. Флаг, а не параметр, потому что
 // addChatEntry зовут из десятка мест и протаскивать признак через все — шум.
 // NB: объявлен выше, рядом с _chatFollow — _trimChatNodes читает его раньше этой строки,
 // а `let` не поднимается: обращение до инициализации бросило бы ReferenceError.
 
 function _renderHistory(agent, rows) {
     _chatTrimLimit = MAX_CHAT_NODES;
     const meta = chatLogs[agent] = _newChatLogState();
     const chat = $('#chat');


## Later history of the touched files on main (after this commit)

25 later commits touch these paths; the first 40 (oldest first):
d3e19cc4c 2026-09-22 Чат: дозагрузка истории порциями по 100 сообщений вместо 500
8941811c9 2026-09-22 V-610: rewrite third-party code in app/ with own implementation
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
9c5e64087 2026-09-23 V-621: WIP #V-621: каталог проектов — файл на каждый scope вместо одного общего
7556cfa7c 2026-09-23 V-626: #V-626: implement owner activity telemetry
413144544 2026-09-24 fix: clear chat upload error on agent switch
7ae410f8d 2026-09-24 V-621: разбить общий каталог проектов на файлы по scope
9035836a0 2026-09-25 V-636: схемы функций для GigaChat без nullable/пустых object, панель допуска скрыта вне owner mode, текст про OpenRouter у харнеса нейтральный
b0ef26aa5 2026-09-25 История чата дозагружается страницами по 100 до начала, а не один раз
c4d36776d 2026-09-29 V-658: WIP #V-658: switch default Sonnet to 5.5 pending full tests
87f4ffd1e 2026-09-29 V-672: #V-672: group compaction activity in chat
4321ff7a8 2026-10-02 V-621, V-679: разбить общий каталог проектов на файлы по scope
8155e9d1f 2026-10-04 V-688: add dashboard video playback and GIF previews
3e82520ec 2026-10-05 дашборд: кнопка «открыть в новой вкладке» для PDF и прочих файлов, PDF во фрейме просмотрщика
6057d1e11 2026-10-05 V-706: #V-706: fix session API and delivery lifecycle
86bb4e238 2026-10-07 V-753: #V-753: fix dashboard TG topic toggle persistence
b02e52f23 2026-10-08 V-757: #V-757: add Claude Haiku 5.5
8efc5e034 2026-10-11 V-820: #V-820: show hidden orchestrator status and cache
0059e6757 2026-10-13 V-621: разбить общий каталог проектов на файлы по scope
66121be42 2026-10-15 V-858: implement dashboard info panel and task approvals
59cf84d21 2026-10-15 V-863: #V-863: restore unread dots on orchestrator tabs
f8bdbeee3 2026-10-15 V-871: show full proposal details and deliver owner decisions
b45042823 2026-10-15 V-873: remove proposal cards and child work summary
edfac4356 2026-10-15 V-876: WIP #V-876: design tokens, theme.js, model/status badges from one source
344cc8866 2026-10-15 V-875: #V-875: step estimates, persistent per-step timing, estimate-based reminders

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### d3e19cc4c Чат: дозагрузка истории порциями по 100 сообщений вместо 500

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e025c6fff..aebb1c2d4 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1239,11 +1239,11 @@ function _addLoadMoreBtn() {
     if ($('#load-more-btn')) return;
     const btn = document.createElement('button');
     btn.type = 'button';
     btn.id = 'load-more-btn';
     btn.className = 'w-full text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
-    btn.textContent = T('▲ Load previous 500');
+    btn.textContent = T('▲ Load previous 100');
     btn.addEventListener('click', loadMoreLogs);
     $('#chat').prepend(btn);
 }
 function updateLoadMoreBtn() {
     const meta = chatLogs[selectedAgent];
@@ -1267,11 +1267,11 @@ async function loadMoreLogs() {
     if (btn) { btn.textContent = T('⏳ Loading previous messages…'); btn.disabled = true; }
     try {
         const q = new URLSearchParams({
             scope: targetScope,
             before_id: String(firstId),
-            limit: '500',
+            limit: '100',
             cap: String(_CHAT_ROW_CAP),
         });
         const logs = await api(
             `/api/sessions/${encodeURIComponent(targetAgent)}/logs?${q}`,
             {
@@ -1314,11 +1314,11 @@ async function loadMoreLogs() {
             _replayingHistory = false;
         }
         chat.scrollTop = chat.scrollHeight - oldHeight;
     } catch (e) {
         if (!_chatLoadIsCurrent(targetGeneration, targetAgent, targetScope)) return;
-        if (btn) { btn.textContent = T('▲ Load previous 500'); btn.disabled = false; }
+        if (btn) { btn.textContent = T('▲ Load previous 100'); btn.disabled = false; }
         console.warn('loadMoreLogs error:', e);
     }
 }
 
 
### 8941811c9 V-610: rewrite third-party code in app/ with own implementation

diff --git a/app/static/js/app.js b/app/static/js/app.js
index aebb1c2d4..bd468d27c 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2139,55 +2139,18 @@ function initTabContextMenu() {
             renderOrchTabs(orchData);
         }));
         menu.appendChild(mkItem(T('📁 Change folder'), '#60a5fa', () => {
             changeOrchScope(name, scope);
         }));
-        menu.appendChild(mkItem(T('🗑 Delete'), '#ef4444', () => {
-            openDeleteOrchModal(name, scope);
-        }));
+        menu.appendChild(mkItem(T('🗑 Delete'), '#ef4444', () => confirmOrchestratorDelete(name, scope)));
         document.body.appendChild(menu);
         const rect = menu.getBoundingClientRect();
         if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
         if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
     });
 }
 
-function openDeleteOrchModal(name, scope) {
-    const modal = $('#delete-orch-modal');
-    if (!modal) {
-        if (!confirm(T('Delete "{name}" and all its workers?', {name}))) return;
-        api(`/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' })
-            .then(() => loadOrchestrators())
-            .catch(e => alert(`Delete failed: ${e.message}`));
-        return;
-    }
-    $('#delete-orch-name').textContent = `"${name}"`;
-    $('#delete-tg-topics').checked = false;
-    modal.classList.remove('hidden');
-    modal.classList.add('flex');
-
-    const close = () => {
-        modal.classList.add('hidden');
-        modal.classList.remove('flex');
-    };
-
-    $('#delete-orch-confirm').onclick = async () => {
-        const deleteTopics = $('#delete-tg-topics').checked;
-        close();
-        try {
-            const url = `/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}&delete_tg_topics=${deleteTopics}`;
-            await api(url, { method: 'DELETE' });
-            loadOrchestrators();
-        } catch (e) {
-            alert(`Delete failed: ${e.message}`);
-        }
-    };
-    $('#delete-orch-cancel').onclick = close;
-    $('#delete-orch-modal-close').onclick = close;
-    modal.onclick = (e) => { if (e.target === modal) close(); };
-}
-
 function changeOrchScope(name, oldScope) {
     const modal = $('#change-scope-modal');
     if (!modal) return;
     const pathInput = $('#change-scope-path');
     const errorEl = $('#change-scope-error');
@@ -2257,10 +2220,44 @@ function changeOrchScope(name, oldScope) {
     $('#change-scope-confirm').addEventListener('click', confirmHandler);
     browseBtn.addEventListener('click', onBrowse);
     modal.addEventListener('click', (e) => { if (e.target === modal) { close(); cleanup(); } }, { once: true });
 }
 
+// Диалог подтверждения собирается на время одного ответа и удаляется целиком:
+// галочка TG-топиков каждый раз начинается снятой, а обработчики не копятся.
+function confirmOrchestratorDelete(name, scope) {
+    const overlay = document.createElement('div');
+    overlay.className = 'fixed inset-0 bg-black/60 backdrop-filter backdrop-blur-sm z-50 flex items-center justify-center';
+    overlay.innerHTML = `
+        <div class="glass glow rounded-xl p-6 w-[380px]">
+            <div class="flex items-center justify-between mb-4">
+                <h2 class="text-sm font-bold">${escHtml(T('Delete Orchestrator'))}</h2>
+                <button data-act="cancel" class="text-slate-500 hover:text-white text-lg">✕</button>
+            </div>
+            <p class="text-xs text-slate-300 mb-4">${escHtml(T('Delete "{name}" and all its workers?', {name}))}</p>
+            <label class="flex items-center gap-2 mb-4 cursor-pointer text-xs text-slate-400">
+                <input data-role="tg-topics" type="checkbox" class="accent-indigo-500">
+                ${escHtml(T('Also delete associated TG topics'))}
+            </label>
+            <div class="flex gap-2">
+                <button data-act="cancel" class="flex-1 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-xs transition-colors">${escHtml(T('Cancel'))}</button>
+                <button data-act="delete" class="flex-1 px-3 py-2 bg-red-900 hover:bg-red-800 rounded-lg text-xs font-medium transition-colors">${escHtml(T('Delete'))}</button>
+            </div>
+        </div>`;
+    overlay.addEventListener('click', (e) => {
+        const act = e.target === overlay ? 'cancel' : e.target.closest('[data-act]')?.dataset.act;
+        if (!act) return;
+        const withTopics = overlay.querySelector('[data-role="tg-topics"]').checked;
+        overlay.remove();
+        if (act !== 'delete') return;
+        const query = new URLSearchParams({ scope, delete_tg_topics: String(withTopics) });
+        api(`/api/orchestrators/${name}?${query}`, { method: 'DELETE' })
+            .then(() => loadOrchestrators(), (err) => alert(`Delete failed: ${err.message}`));
+    });
+    document.body.appendChild(overlay);
+}
+
 function _updateHiddenBtn() {
     const btn = $('#hidden-tabs-btn');
     if (!btn) return;
     const hidden = _getHiddenTabs();
     const hasHidden = [...hidden].some(n => orchData.find(o => o.name === n));
### de5d62a52 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта

diff --git a/app/static/js/app.js b/app/static/js/app.js
index bd468d27c..101acf586 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1015,11 +1015,10 @@ document.addEventListener('DOMContentLoaded', () => {
     _initPollingVisibility();
     scheduleRefresh();
     initFilePreviewModal();
     initUsageBar();
     QuotaPanel.init();
-    PortfolioPanel.init();
     Connection.init();
     _startCacheCountdown();
 });
 
 let eventSource = null;
@@ -2511,11 +2510,10 @@ async function onOrchestratorChange() {
     // (sessions+stats, затем orchestrators), а нам для показа чата не нужно ни одного (D2).
     _showChatFor(selectedAgent, currentScope);
     refreshSessions();
     initFilePanel();
     if (_tasksTabActive) loadTasks();
-    if (_portfolioTabActive) PortfolioPanel.load();
     if (_jobsTabActive) loadJobs();
 }
 
 // === Agent Selection ===
 async function selectAgent(name) {
@@ -3325,11 +3323,11 @@ async function refreshOpenFolders() {
 function initFilePanel() {
     const tree = $('#file-tree');
 
     if (currentScope) {
         loadFileTree(currentScope, tree);
-        if (!_tasksTabActive && !_jobsTabActive && !_portfolioTabActive) {
+        if (!_tasksTabActive && !_jobsTabActive) {
             _pollRegister('files', refreshOpenFolders, 10000);
             _pollWake('files');
         } else _pollStop('files');
     } else {
         _pollStop('files');
@@ -3661,285 +3659,10 @@ function _parseRateLimitStatus(content) {
 // === Tasks Panel ===
 let _tasksTabActive = false;
 
 let _jobsTabActive = false;
 
-let _portfolioTabActive = false;
-
-const PortfolioPanel = (() => {
-    let requestGeneration = 0;
-    let currentPayload = {projects: []};
-    let operatorCsrf = '';
-    const openDisclosures = new Set();
-
-    const _terminalStatuses = new Set(['done', 'paid', 'cancelled']);
-    const _queueStatuses = new Set(['new', 'backlog']);
-
-    function init() {
-        if (document.querySelector('[data-left-tab="portfolio"]')) return;
-        const folderButton = document.getElementById('open-folder-btn');
-        const tabs = folderButton?.parentElement;
-        if (!tabs) return;
-        const button = document.createElement('button');
-        button.type = 'button';
-        button.dataset.leftTab = 'portfolio';
-        button.className = 'left-tab portfolio-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors';
-        button.textContent = T('PROJECTS');
-        button.title = T('Portfolio projects');
-        button.setAttribute('aria-label', T('Open project board'));
-        button.addEventListener('click', () => switchLeftTab('portfolio'));
-        tabs.insertBefore(button, folderButton);
-    }
-
-    function projectMeta(project) {
-        const owner = project.owner?.name || 'owner missing';
-        const contributors = (project.contributors || []).map(member => member.name).filter(Boolean);
-        const contributorText = contributors.length
-            ? contributors.map(name => `<span class="portfolio-person">+ ${escHtml(name)}</span>`).join('')
-            : `<span class="portfolio-person portfolio-person-muted">${T('no sub')}</span>`;
-        return `<div class="portfolio-project-meta">
-            <span class="portfolio-owner">◆ ${escHtml(owner)}</span>${contributorText}
-        </div>`;
-    }
-
-    function taskNumber(task) {
-        const number = task.task_display_number ?? task.par_number ?? task.par ?? task.id;
-        return task.ref_prefix ? `${task.ref_prefix}-${number}` : number;
-    }
-
-    function waitsForTask(project, task) {
-        const stableId = task.task_stable_id || '';
-        if (!stableId) return [];
-        return (project.waits || []).filter(wait =>
-            wait.status === 'open' && wait.task_stable_id === stableId
-        );
-    }
-
-    function taskCard(project, task, kind) {
-        const waits = waitsForTask(project, task);
-        const par = String(taskNumber(task));
-        const namespace = task.task_namespace_id || project.task_namespace_id || '';
-        const stableId = task.task_stable_id || '';
-        const waitAttrs = waits.length
-            ? ' data-wait-open="true"'
-            : ' data-wait-open="false"';
-        return `<button type="button" class="portfolio-road-task"
-            data-road-task="true" data-road-task-kind="${escHtml(kind)}"
-            data-task-par="${escHtml(par)}" data-task-project="${escHtml(namespace)}"
-            data-task-status="${escHtml(task.status || '')}"
-            data-task-stable-id="${escHtml(stableId)}"${waitAttrs}>
-            <span class="portfolio-road-task-ref">#${escHtml(par)}</span>
-            <strong>${escHtml(task.title || T('Untitled'))}</strong>
-            <small>${escHtml(task.status || 'unknown')}</small>
-            ${waits.map(wait => `<em>${T('NEED REPLY · {question}', {question: escHtml(wait.question)})}</em>`).join('')}
-        </button>`;
-    }
-
-    function markerTarget(project, stageOrder, staged, unassigned) {
-        let target = '';
-        for (const label of stageOrder) {
-            if ((staged.get(label) || []).some(task => task.status === 'in_progress')) {
-                target = label;
-            }
-        }
-        if (target) return `stage:${target}`;
-        for (const label of stageOrder) {
-            if ((staged.get(label) || []).some(task => _queueStatuses.has(task.status))) {
-                return `stage:${label}`;
-            }
-        }
-        if (unassigned.some(task => !_terminalStatuses.has(task.status))) return 'unassigned';
-        return stageOrder.length ? `stage:${stageOrder[stageOrder.length - 1]}` : 'unassigned';
-    }
-
-    function markerHtml(active) {
-        return active ? `<div class="portfolio-road-marker" data-road-marker="true">
-            <i></i><span>${T('we are here')}</span>
-        </div>` : '';
-    }
-
-    function stageHtml(project, label, tasks, marker) {
-        const active = tasks.some(task => task.status === 'in_progress');
-        return `<section class="portfolio-road-stage" data-road-stage="true"
-            data-road-stage-label="${escHtml(label)}" data-stage-active="${active}">
-            <header><span>${escHtml(label)}</span><b>${tasks.length}</b></header>
-            <div class="portfolio-road-stage-tasks">
-                ${tasks.map(task => taskCard(project, task, 'stage')).join('') || `<span class="portfolio-road-empty">${T('empty for now')}</span>`}
### 9c5e64087 V-621: WIP #V-621: каталог проектов — файл на каждый scope вместо одного общего

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 101acf586..38f64f5b8 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2488,10 +2488,12 @@ async function onOrchestratorChange() {
     if (_chatLoadController) _chatLoadController.abort();
     _chatSnapshotReady = false;
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
+    // V-621: чипы тегов другого оркестратора не должны пережить переключение scope.
+    _taskTagFilter.clear();
     const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
     chatLogs = {};
     currentSessions = [];
     resetChatTransientState();
     selectedAgent = opt?.dataset?.name || null;
@@ -3772,31 +3774,35 @@ const COLLAPSED_DEFAULT = new Set(['backlog', 'paid', 'cancelled']);
 let _taskCollapsed = {};
 
 // Выбранные теги проектов. Пусто — задачи текущего scope, как было до V-576.
 const _taskTagFilter = new Set();
 let _taskCatalog = null;
+let _taskCatalogScope = undefined;
 
+// V-621: каталог теперь свой у каждого scope — чужие теги не должны попасть в чипы.
 async function _taskProjectCatalog() {
-    if (_taskCatalog) return _taskCatalog;
+    if (_taskCatalog && _taskCatalogScope === currentScope) return _taskCatalog;
     try {
-        const payload = await api('/api/tm/projects');
+        const payload = await api(`/api/tm/projects?scope=${encodeURIComponent(currentScope || '')}`);
         _taskCatalog = (payload.projects || []).filter(p => !p.archived);
     } catch (e) {
         _taskCatalog = [];
     }
+    _taskCatalogScope = currentScope;
     return _taskCatalog;
 }
 
 async function _loadTasksNow() {
     const panel = document.getElementById('tasks-panel');
     if (!panel) return;
     try {
         const catalog = await _taskProjectCatalog();
         const tags = [..._taskTagFilter];
+        const scopeParam = `scope=${encodeURIComponent(currentScope || '')}`;
         const query = tags.length
-            ? `tags=${encodeURIComponent(tags.join(','))}`
-            : `scope=${encodeURIComponent(currentScope || '')}`;
+            ? `tags=${encodeURIComponent(tags.join(','))}&${scopeParam}`
+            : scopeParam;
         const data = await api(`/api/tm/tasks?${query}`, {pollKey: 'tasks'});
         renderTasksPanel(panel, data, catalog);
     } catch (e) {
         panel.innerHTML = `<div class="p-2 text-slate-500">${T('Failed to load tasks')}</div>`;
     }
### 7556cfa7c V-626: #V-626: implement owner activity telemetry

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 38f64f5b8..cddd09b06 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -899,10 +899,11 @@ function restoreDraft() {
     }
 }
 
 
 document.addEventListener('DOMContentLoaded', () => {
+    window.OrchestraOwnerActivity?.init();
     $('#send-btn').addEventListener('click', sendChat);
     $('#send-after-turn-btn').addEventListener('click', () => sendChat({afterTurn: true}));
     window._queuedMessagesTimer = setInterval(() => refreshQueuedMessages(), 5000);
     $('#stop-btn').addEventListener('click', stopAgent);
     $('#chat-input').addEventListener('keydown', (e) => {
@@ -2488,10 +2489,11 @@ async function onOrchestratorChange() {
     if (_chatLoadController) _chatLoadController.abort();
     _chatSnapshotReady = false;
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
+    window.OrchestraOwnerActivity?.setScope(currentScope);
     // V-621: чипы тегов другого оркестратора не должны пережить переключение scope.
     _taskTagFilter.clear();
     const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
     chatLogs = {};
     currentSessions = [];
### 413144544 fix: clear chat upload error on agent switch

diff --git a/app/static/js/app.js b/app/static/js/app.js
index cddd09b06..25debe48b 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2526,10 +2526,11 @@ async function selectAgent(name) {
     _captureChatReadFrontier();
     if (eventSource) { eventSource.close(); eventSource = null; }
     resetChatTransientState();
     selectedAgent = name;
     _hideRateLimitBanner();
+    _showChatDropError('');
     $('#chat').innerHTML = '';
     _prepareChatAnchorRestore(false);
     updateInputState();
     restoreDraft();
     refreshQueuedMessages();
### 7ae410f8d V-621: разбить общий каталог проектов на файлы по scope

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 25debe48b..c76d51252 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2637,14 +2637,20 @@ function _historyTransferMessage(transfer) {
         return {
             type: 'status',
             text: 'native provider thread resumed after total-context preflight',
         };
     }
-    if (transfer.mode === 'fresh') {
+    if (transfer.mode === 'native_in_place') {
         return {
             type: 'status',
-            text: 'fresh target session started; previous dialog discarded',
+            text: 'native session preserved',
+        };
+    }
+    if (transfer.mode === 'chat_history_v1') {
+        return {
+            type: 'status',
+            text: `chat_history_v1 transferred ${transfer.chars || 0} chars`,
         };
     }
     if (transfer.mode === 'summary') {
         return {
             type: 'warning',
### 9035836a0 V-636: схемы функций для GigaChat без nullable/пустых object, панель допуска скрыта вне owner mode, текст про OpenRouter у харнеса нейтральный

diff --git a/app/static/js/app.js b/app/static/js/app.js
index c76d51252..cab995434 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2821,11 +2821,11 @@ function formatContext(ctx) {
     const total = ctx.total_tokens || 0;
     const max = ctx.max_tokens || 0;
     const totalK = total > 1000 ? `${(total/1000).toFixed(0)}k` : total;
     const maxK = max > 1000 ? `${(max/1000).toFixed(0)}k` : max;
     let s = `${pct}% (${totalK}/${maxK})`;
-    if (ctx.cache_hit !== undefined) s += ` · cache ${Number(ctx.cache_hit).toFixed(2)}%`;
+    if (ctx.cache_hit !== undefined) s += ` · ${T('cache')} ${Number(ctx.cache_hit).toFixed(2)}%`;
     return s;
 }
 
 async function _fetchAgentContextNow(name, scope) {
     if (!scope) return;