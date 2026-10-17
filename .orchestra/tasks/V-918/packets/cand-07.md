# Candidate cand-07

## ORIGIN commit d327b4bf5e (2026-06-10): add WHY-only comments to frontend files
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 922128ea2..fa6e74907 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1,17 +1,20 @@
+// Cap DOM nodes to avoid memory growth during long agent sessions
 const MAX_CHAT_NODES = 500;
 let currentScope = null;
 let selectedAgent = null;
 let chatLogs = {};
+// localMessages tracks messages sent from this tab so SSE echo doesn't create duplicates
 let localMessages = new Set();
 let pendingUserMsgs = [];
 let pendingBubble = null;
 let uiDebounceTimer = null;
 let refreshController = null;
+// UI debounce: rapid-fire messages from the user are batched into one send before the timer fires
 const UI_DEBOUNCE_MS = 2500;
 let scrollAfterLoad = true;
 let drafts = {};
 
 window.compactMode = localStorage.getItem('compactToolMode') === 'true';
 
 function saveDraft() {
     if (selectedAgent) drafts[selectedAgent] = { text: $('#chat-input').value, images: [...pastedImages] };
@@ -133,26 +136,30 @@ let eventSource = null;
 
 function scheduleRefresh() {
     setTimeout(async () => {
         await refreshSessions();
         scheduleRefresh();
     }, 3000);
 }
 
+// SSE reconnects on error — server may restart mid-session, don't lose the log stream
 function connectSSE() {
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (!selectedAgent || !currentScope) return;
     const lastId = chatLogs[selectedAgent]?.lastId || 0;
+    // On first connect (lastId=0), fetch the last 100 messages for initial display
     const limitParam = lastId === 0 ? '&limit=100' : '';
     const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
     eventSource = new EventSource(url);
     eventSource.onmessage = (event) => {
         try {
             const l = JSON.parse(event.data);
+            // When the server echoes back a message we sent, replace our optimistic bubble
+            // with the confirmed version so timestamps and content match exactly.
             const isLocal = l.type === 'user_message' && (localMessages.has(l.content) || [...localMessages].some(m => l.content.endsWith(m)));
             if (isLocal) {
                 localMessages.delete(l.content);
                 for (const m of localMessages) { if (l.content.endsWith(m)) { localMessages.delete(m); break; } }
                 if (pendingBubble) {
                     pendingBubble.remove();
                     pendingBubble = null;
                     pendingUserMsgs = [];
@@ -261,18 +268,18 @@ async function loadProfilesDropdown() {
         const select = $('#orch-profile');
         select.innerHTML = '';
         for (const p of profiles) {
             const opt = document.createElement('option');
             opt.value = p.name;
             opt.textContent = `${p.name} (${p.config_dir || 'env процесса'})`;
             select.appendChild(opt);
         }
-        // B5: API сортирует по name (ORDER BY name), поэтому первый ≠ personal.
-        // Явно предпочитаем personal, иначе — первый по списку.
+        // API sorts by name (ORDER BY name), so first entry ≠ 'personal'.
+        // Prefer 'personal' explicitly; fall back to whatever comes first.
         const def = profiles.find(p => p.name === 'personal') || profiles[0];
         if (def) select.value = def.name;
     } catch {}
 }
 
 async function loadPipelinesDropdown() {
     try {
         const pipelines = await api('/api/pipelines');
@@ -946,16 +953,17 @@ function updateOrchTabDots() {
 
 function selectOrchestrator(name, scope) {
     _unreadTabs.delete(scope);
     const picker = $('#orch-picker');
     picker.value = scope;
     const opt = [...picker.options].find(o => o.dataset.name === name);
     if (opt) picker.selectedIndex = opt.index;
 
+    // Keep last 10 recently used orchestrators — used to sort tabs on next load
     const recent = JSON.parse(localStorage.getItem('recentOrchs') || '[]');
     const filtered = recent.filter(n => n !== name);
     filtered.unshift(name);
     localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));
 
     onOrchestratorChange();
     renderOrchTabs(orchData);
 }
@@ -1100,20 +1108,22 @@ function updateAgentInfo(session) {
         changeBtn = document.createElement('span');
         changeBtn.id = 'ai-model-change';
         changeBtn.style.cssText = 'cursor:pointer;font-size:10px;margin-left:4px;color:#475569;transition:color 0.15s';
         changeBtn.textContent = '⇄';
         changeBtn.addEventListener('mouseenter', () => changeBtn.style.color = '#94a3b8');
         changeBtn.addEventListener('mouseleave', () => changeBtn.style.color = '#475569');
         modelEl.parentElement.appendChild(changeBtn);
     }
+    // Model can only be changed when the CLI is not actively processing — changing mid-turn would be ignored by the SDK
     const isIdle = session.status === 'idle' || session.status === 'stopped' || session.status === 'waiting';
     changeBtn.style.display = isIdle ? 'inline' : 'none';
     changeBtn.onclick = () => _showModelPicker(session.name, session.model, changeBtn);
     $('#ai-role').textContent = session.role || 'worker';
+    // Cost is virtual (API-equivalent), not real spend — subscription model
     $('#ai-cost').textContent = `$${(session.cost_usd || 0).toFixed(2)}`;
     $('#ai-cost').title = `$${(session.cost_usd || 0).toFixed(4)} (CLI cost, includes cache)`;
     $('#ai-branch').textContent = session.branch || '-';
     $('#ai-scope').textContent = session.scope || '-';
     const descEl = $('#ai-desc'); const descLabel = $('#ai-desc-label');
     if (descEl && descLabel) {
         if (session.description) { descEl.textContent = session.description; descEl.title = session.description; descEl.classList.remove('hidden'); descLabel.classList.remove('hidden'); }
         else { descEl.classList.add('hidden'); descLabel.classList.add('hidden'); }
@@ -1200,16 +1210,17 @@ function renderAgentList(sessions) {
         if (pn && byName.has(pn)) {
             if (!childrenMap.has(pn)) childrenMap.set(pn, []);
             childrenMap.get(pn).push(s);
         } else {
             roots.push(s);
         }
     }
 
+    // Guard against cycles in the parent/child graph — shouldn't happen but the data comes from DB
     const seen = new Set();
     const buildNode = (session, isChild, isLast) => {
         if (seen.has(session.name)) return null;
         seen.add(session.name);
         const wrapper = document.createElement('div');
         wrapper.className = 'tree-node' + (isChild ? ' tree-child' : '') + (isLast ? ' tree-last' : '');
         wrapper.appendChild(createAgentItem(session));
         const kids = childrenMap.get(session.name) || [];
@@ -1232,16 +1243,17 @@ function renderAgentList(sessions) {
         if (!seen.has(s.name)) {
             seen.add(s.name);
             const node = buildNode(s, false, false);
             if (node) list.appendChild(node);
         }
     }
 }
 
+// Static defaults — server may extend these with custom pipeline roles at startup
 let _roleIcons = {'orchestrator':'👑','worker':'⚙️','full-cycle':'🔄','sub-orchestrator':'🎯','reviewer':'🔍','watcher':'👁️'};
 fetch('/api/role-icons').then(r=>r.json()).then(d=>{_roleIcons={..._roleIcons,...d}}).catch(()=>{});
 
 function createAgentItem(s) {
     const isSelected = s.name === selectedAgent;
     const isDead = s.status === 'stopped' || s.status === 'error';
     const item = document.createElement('div');
     item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
@@ -1323,16 +1335,19 @@ function createAgentItem(s) {
     }
     item.append(icon, info);
 
     if (isSelected) updateAgentInfo(s);
     return item;
 }
 
 // === Chat ===
+// Optimistic UI: show message immediately, debounce actual send so rapid
+// follow-up messages get batched. The server echoes back via SSE which
+// replaces the bubble with the canonical version.
 async function sendChat() {
     const input = $('#chat-input');
     const msg = input.value.trim();
     if (!msg || !currentScope || !selectedAgent) return;
     input.value = '';
     clearPastePreview();
 
     pendingUserMsgs.push(msg);
@@ -1801,22 +1816,25 @@ function _findLastBefore(parent, selector, anchor) {
     while (node) {
         if (node.matches(selector)) return node;
         node = node.previousElementSibling;
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
+// Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
+// anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 function addChatEntry(type, content, ts, anchor) {
     if (HIDE_THINKING && type === 'thinking') return;
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     const _insert = (el) => anchor ? chat.insertBefore(el, anchor) : chat.appendChild(el);
 
+    // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
     const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);
 
     if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
         const div = document.createElement('div');
         div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
         const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
         if (b64Match) {
             const img = document.createElement('img');
@@ -1908,21 +1926,23 @@ function addChatEntry(type, content, ts, anchor) {
         }
         if (streamBubble) {
             streamBubble = null;
             streamContent = '';
         }
         const line = buildCompactToolLine(type, content, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(line);
+        // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
         while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
         if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
+    // Stream events accumulate into one bubble that gets re-rendered on each chunk
     if (type === 'stream') {
         removeWaitingIndicator();
         streamContent += content;
         if (!streamBubble) {
             streamBubble = document.createElement('div');
             streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body';
             streamBubble.style.position = 'relative';
             const agentColor = agentColors[selectedAgent];
@@ -1930,24 +1950,26 @@ function addChatEntry(type, content, ts, anchor) {
             _insert(streamBubble);
         }
         streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
+    // 'text' event signals that streaming finished — finalize the bubble with timestamp/copy
     if (type === 'text' && streamBubble) {
         addCopyBtn(streamBubble, streamContent);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
         return;
     }
 
+    // Any non-text log after a stream (e.g. tool call) also terminates the stream bubble
     if (streamBubble && type !== 'text') {
         addCopyBtn(streamBubble, streamContent);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
     }
 
     if (type === 'status') {
@@ -2020,16 +2042,18 @@ function addChatEntry(type, content, ts, anchor) {
         type === 'user_message' ? 'chat-user ml-16' :
         type === 'tool' ? 'chat-tool' :
         type === 'tool_result' ? 'chat-tool-result' :
         type === 'error' ? 'text-red-400 text-xs' :
         'chat-bot markdown-body'
     }`;
     if (type === 'user_message') {
         content = content.replace(/^\[\d{2}:\d{2}\] /, '');
+        // [from:agent-name] prefix means this was an agent-to-agent message injected by the MCP send_message tool,
+        // not a human message — style it differently (colored border, sender label)
         const fromMatch = content.match(/^\[from:(.+?)\]\s*([\s\S]*)$/);
         if (fromMatch) {
             const sender = fromMatch[1];
             const msg = fromMatch[2];
             const senderColor = agentColors[sender] || Object.entries(agentColors).find(([k]) => k.startsWith(sender))?.[1] || '#64748b';
             div.style.borderLeft = `3px solid ${senderColor}`;
             div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
             const label = document.createElement('div');
@@ -3669,16 +3693,17 @@ const FILE_ICONS = {
 };
 
 function getFileIcon(name, isDir) {
     if (isDir) return '📁';
     const ext = name.split('.').pop().toLowerCase();
     return FILE_ICONS[ext] || '📄';
 }
 
+// Keyed by scope so each project remembers its own expanded folders independently
 function _getExpandedFolders() {
     try { return new Set(JSON.parse(localStorage.getItem('expandedFolders_' + currentScope) || '[]')); } catch { return new Set(); }
 }
 function _saveExpandedFolder(path, expanded) {
     const set = _getExpandedFolders();
     if (expanded) set.add(path); else set.delete(path);
     localStorage.setItem('expandedFolders_' + currentScope, JSON.stringify([...set]));
 }
@@ -3841,23 +3866,25 @@ function initFilePanel() {
     if (currentScope) {
         loadFileTree(currentScope, tree);
     }
     if (_fileRefreshInterval) clearInterval(_fileRefreshInterval);
     _fileRefreshInterval = setInterval(refreshOpenFolders, 10000);
 }
 
 // === Refresh Loop ===
-let refreshInProgress = false;
+let refreshInProgress = false; // single-flight guard — skips if previous refresh is still in flight
 async function refreshSessions() {
     if (refreshInProgress) return;
     refreshInProgress = true;
+    // Abort previous in-flight refresh so stale responses don't overwrite newer data
     if (refreshController) refreshController.abort();
     refreshController = new AbortController();
     const signal = refreshController.signal;
+    // Capture scope at call time — guard below checks it didn't change while we were fetching
     const capturedScope = currentScope;
 
     try {
         if (!capturedScope) return;
 
         const [sessions, stats] = await Promise.all([
             api(`/api/sessions?scope=${encodeURIComponent(capturedScope)}`, { signal }),
             api(`/api/stats?scope=${encodeURIComponent(capturedScope)}`, { signal }),
@@ -3898,16 +3925,17 @@ async function refreshSessions() {
     } catch (e) {
         if (e.name !== 'AbortError') { console.warn('refresh error:', e); _onServerError(); }
     } finally {
         refreshInProgress = false;
     }
 }
 
 // === API ===
+// 5s timeout on all API calls — prevents hanging tabs when the server restarts mid-fetch
 async function api(url, opts = {}) {
     const timeout = AbortSignal.timeout(5000);
     const signals = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
     const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts, signal: signals });
     if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
     return resp.json();
 }
 
@@ -3943,16 +3971,17 @@ async function _pollReconnect() {
         await new Promise(r => setTimeout(r, 2000));
         try {
             const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
             if (r.status < 502) { location.reload(); return; }
         } catch {}
     }
 }
 
+// Two consecutive failures before showing overlay — one transient error shouldn't panic the UI
 function _onServerError() {
     _rebootFails++;
     if (_rebootFails >= 2) _showRebootOverlay();
 }
 
 function _onServerOk() {
     _rebootFails = 0;
 }
@@ -4000,16 +4029,17 @@ const STATUS_ORDER = ['in_progress', 'done', 'new', 'backlog', 'paid', 'cancelle
 const STATUS_COLORS = {
     in_progress: 'bg-blue-400', done: 'bg-amber-400', new: 'bg-white',
     backlog: 'bg-slate-500', paid: 'bg-emerald-400', cancelled: 'bg-red-400',
 };
 const STATUS_LABELS = {
     in_progress: 'IN PROGRESS', done: 'DONE', new: 'NEW',
     backlog: 'BACKLOG', paid: 'PAID', cancelled: 'CANCELLED',
 };
+// These statuses are collapsed by default — they're historical/archive, not actionable
 const COLLAPSED_DEFAULT = new Set(['backlog', 'paid', 'cancelled']);
 let _taskCollapsed = {};
 
 async function loadTasks() {
     const panel = document.getElementById('tasks-panel');
     if (!panel) return;
     try {
         const scope = currentScope || '';
diff --git a/app/static/js/tool-renderers.js b/app/static/js/tool-renderers.js
index 5621c7513..329ba4560 100644
--- a/app/static/js/tool-renderers.js
+++ b/app/static/js/tool-renderers.js
@@ -26,16 +26,18 @@ function toolIcon(name) {
 function toolShortName(name) {
     if (name.startsWith('mcp__')) {
         const parts = name.split('__');
         return parts.length >= 3 ? parts[2] : name;
     }
     return name;
 }
 
+// Returns null when lines are too different (< 40% common chars) — fall back to plain del/add
+// rather than showing character-level diff noise on completely replaced lines.
 function _inlineDiff(oldLine, newLine) {
     const dmp = new diff_match_patch();
     const diffs = dmp.diff_main(oldLine, newLine);
     dmp.diff_cleanupSemantic(diffs);
     let common = 0, total = 0;
     for (const [op, text] of diffs) { total += text.length; if (op === 0) common += text.length; }
     if (total === 0 || common / total < 0.4) return null;
     let delHtml = '', addHtml = '';
@@ -43,16 +45,18 @@ function _inlineDiff(oldLine, newLine) {
         const esc = _escHtml(text);
         if (op === 0) { delHtml += esc; addHtml += esc; }
         else if (op === -1) delHtml += `<span style="background:rgba(239,68,68,0.35);border-radius:2px">${esc}</span>`;
         else addHtml += `<span style="background:rgba(34,197,94,0.35);border-radius:2px">${esc}</span>`;
     }
     return { delHtml, addHtml };
 }
 
+// LCS-based diff — Uint16Array saves memory vs plain Array for large files.
+// Walks the DP table backwards to reconstruct the edit sequence.
 function buildDiffLines(oldStr, newStr) {
     const a = oldStr.split('\n'), b = newStr.split('\n');
     const n = a.length, m = b.length;
     const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
     for (let i = 1; i <= n; i++)
         for (let j = 1; j <= m; j++)
             dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
     const raw = [];
@@ -139,22 +143,25 @@ function renderEditDiff(body) {
         moreEl.textContent = `▼ ${restLines.length} more lines`;
         moreEl.dataset.count = restLines.length;
         container.appendChild(moreEl);
     }
 
     return container;
 }
 
+// Renders a placeholder skeleton while the tool_result (file content) is still in flight.
+// The skeleton gets replaced by actual content when the SSE stream delivers tool_result.
 function renderReadView(body) {
     let data;
     try { data = JSON.parse(body); } catch { return null; }
     if (!data.file_path) return null;
 
     const fp = data.file_path || '';
+    // Strip worktree prefix — full absolute paths are too noisy for the UI
     const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;
     const offset = data.offset || 0;
     const limit = data.limit || '';
 
     const container = document.createElement('div');
     container.className = 'diff-view';
     container.dataset.readPath = fp;
 
@@ -276,16 +283,18 @@ function _wsCompactLinks(links) {
         a.onmouseenter = () => a.style.color = '#94a3b8';
         a.onmouseleave = () => a.style.color = '#64748b';
         a.textContent = `[${i + 1}] ${title || domain}${title && domain ? ' — ' + domain : ''}`;
         div.appendChild(a);
     }
     return div.children.length > 0 ? div : null;
 }
 
+// Wraps web search results in a collapsible — search results can be very long,
+// and most of the time the first 5 lines are enough to decide if the result is useful.
 function _wsCollapsible(el) {
     const PREVIEW_LINES = 5;
     const PREVIEW_HEIGHT = PREVIEW_LINES * 18;
     const body = el.querySelector('.markdown-body');
     if (!body) return el;
 
     const wrapper = document.createElement('div');
     wrapper.className = 'websearch-results';
@@ -295,43 +304,48 @@ function _wsCollapsible(el) {
 
     const hint = document.createElement('div');
     hint.style.cssText = 'color:#38bdf8;font-size:10px;cursor:pointer;margin-top:4px';
     hint.textContent = '▼ expand';
     let expanded = false;
 
     const linksEl = wrapper.querySelector('[style*="border-top"]');
 
+    // Hide citation links by default — they clutter the preview; shown only when expanded
     if (linksEl) linksEl.style.display = 'none';
 
     const toggleWs = () => {
         expanded = !expanded;
         body.style.maxHeight = expanded ? 'none' : PREVIEW_HEIGHT + 'px';
         body.style.overflowY = expanded ? 'visible' : 'hidden';
         hint.textContent = expanded ? '▲ collapse' : '▼ expand';
         if (linksEl) linksEl.style.display = expanded ? 'block' : 'none';
     };
 
     if (linksEl) wrapper.appendChild(linksEl);
     wrapper.appendChild(hint);
     wrapper.style.cssText = 'cursor:pointer;overflow-x:hidden;max-width:100%';
     wrapper.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleWs(); });
 
+    // rAF defers height check until after the element is in the DOM and has a real offsetHeight
     requestAnimationFrame(() => {
         if (body.scrollHeight <= PREVIEW_HEIGHT + 4) {
             hint.style.display = 'none';
             body.style.maxHeight = 'none';
             body.style.overflowY = 'visible';
             if (linksEl) linksEl.style.display = 'block';
         }
     });
 
     return wrapper;
 }
 
+// Multi-format parser: handles Perplexity sonar JSON, Brave/SerpAPI results arrays,
+// raw text with embedded "Links: [...]" JSON, and Markdown-formatted search responses.
+// Falls back gracefully — each branch returns null and the next tries.
 function renderWebSearchResults(raw) {
     let data;
     try { data = JSON.parse(raw); } catch { data = null; }
 
     if (data) {
         if (data.result && typeof data.result === 'string') {
             const el = document.createElement('div');
             const body = document.createElement('div');
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index bdcda722c..31a0360de 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -1,23 +1,26 @@
 /* usage.js — usage bar rendering, sparklines, countdown. Loaded before app.js. */
 
 let _usageData = null;
 let _usageError = false;
 let _usageCountdownInterval = null;
 
+// Color encodes pace vs. ideal burn rate: green = under budget, red = over,
+// yellow = on track. When resetPct is known, diff drives color rather than raw %.
 function _usageColor(usagePct, resetPct) {
     if (resetPct == null) {
         if (usagePct >= 80) return '#ef4444';
         if (usagePct >= 50) return '#eab308';
         return '#22c55e';
     }
     const diff = usagePct - resetPct;
     if (diff < -10) return '#22c55e';
     if (diff > 10) return '#ef4444';
+    // Smooth hue transition between yellow (60°) and red/green for near-ideal pace
     const hue = Math.max(0, Math.min(120, 60 - diff * 6));
     return `hsl(${hue}, 80%, 50%)`;
 }
 
 function _resetCountdown(isoStr) {
     if (!isoStr) return '';
     const ms = new Date(isoStr) - Date.now();
     if (ms <= 0) return '';
@@ -28,16 +31,18 @@ function _resetCountdown(isoStr) {
 
 function _resetPctNum(isoStr, windowMs) {
     if (!isoStr) return null;
     const remaining = new Date(isoStr) - Date.now();
     const elapsed = windowMs - remaining;
     return Math.max(0, Math.min(100, Math.round(elapsed / windowMs * 100)));
 }
 
+// Computes how long to wait (or "ok") based on pace vs. ideal linear burn.
+// cooldownMin = how many minutes to wait at 0% usage to get back on pace.
 function _paceIndicator(currentPct, isoStr, windowMs) {
     if (!isoStr) return '';
     const remainMs = Math.max(0, new Date(isoStr) - Date.now());
     const elapsedMs = windowMs - remainMs;
     const idealPct = (elapsedMs / windowMs) * 100;
     const delta = currentPct - idealPct;
     if (delta <= 5) return '<span style="color:#22c55e">ok</span>';
     const cooldownMin = Math.round(delta * windowMs / 100 / 60000);
@@ -169,16 +174,17 @@ function renderUsageBar() {
                 _loadSparkline(tip);
             }, 200);
         });
         infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
     }
 }
 
 let _sparkData = null, _sparkDataTs = 0, _spark7dWeekIdx = 0;
+// Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
 async function _loadSparkline(tipEl) {
     const slot = tipEl.querySelector('#usage-sparkline-slot');
     if (!slot) return;
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
             _sparkData = await api('/api/usage/history?hours=336');
             _sparkDataTs = now;
@@ -247,16 +253,18 @@ function _renderSparklines(slot) {
             const ra = d[resetKey]; if (!ra) { ideal.push({ t, v: 0 }); continue; }
             const remain = new Date(ra) - new Date(d.ts);
             const elapsed = windowMs - remain;
             ideal.push({ t, v: Math.max(0, Math.min(100, elapsed / windowMs * 100)) });
         }
         return { pts, ideal };
     };
 
+    // Split history into 7-day billing periods by detecting when resets_at changes.
+    // 1h gap threshold avoids false splits from clock skew or API flakiness.
     const rawWeeks = []; let curWeek = [data[0]];
     for (let i = 1; i < data.length; i++) {
         const prev = data[i-1], cur = data[i];
         const prevReset = prev.seven_day_resets_at, curReset = cur.seven_day_resets_at;
         const isNewPeriod = prevReset && curReset && prevReset !== curReset &&
             new Date(curReset) - new Date(prevReset) > 3600000;
         if (isNewPeriod) {
             rawWeeks.push(curWeek);
@@ -304,13 +312,14 @@ async function fetchUsage() {
     } catch {
         _usageError = true;
     }
     renderUsageBar();
 }
 
 function initUsageBar() {
     fetchUsage();
+    // Full data refresh every 2 minutes; countdown rerender every minute (no API call)
     setInterval(fetchUsage, 120000);
     _usageCountdownInterval = setInterval(() => {
         if (_usageData) renderUsageBar();
     }, 60000);
 }
diff --git a/app/static/js/utils.js b/app/static/js/utils.js
index d4e10fd01..1e92dbc11 100644
--- a/app/static/js/utils.js
+++ b/app/static/js/utils.js
@@ -1,35 +1,40 @@
 /* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */
 
 const CUR = document.body.dataset.currency || '₽';
 const $ = (s) => document.querySelector(s);
 const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');
 
 function _escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
+// DOM-based escaping is safer than regex — handles all edge cases without a lookup table
 function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
 
+// Claude injects XML-style tags (e.g. <thinking>) — strip them before markdown render to avoid display noise
 function _stripXmlTags(text) {
     return text.replace(/<\/?[a-z][a-z0-9_-]*(?:\s[^>]*)?\s*>/gi, '');
 }
 
 marked.setOptions({ breaks: true, gfm: true });
 
+// Remove structural tags DOMPurify would leave as text nodes — they'd break layout if injected via agent output
 DOMPurify.addHook('uponSanitizeElement', (node) => {
     if (['STYLE', 'HTML', 'HEAD', 'BODY', 'META', 'LINK', 'TITLE', 'SCRIPT'].includes(node.tagName)) node.remove();
 });
 
 const _autolinkRe = /(?<!\w)((?:https?:\/\/|ftp:\/\/)[^\s<>\]\)]+|(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:\/[^\s<>\]\)]*)?)(?!\w)/g;
+// Walk only text nodes — skipping A/PRE/CODE avoids double-linking already-linked content and mangling code blocks
 function autolinkText(html) {
     const tmp = document.createElement('div');
     tmp.innerHTML = html;
     const walk = (node) => {
         if (node.nodeType === 3) {
             const t = node.textContent;
             if (!_autolinkRe.test(t)) return;
+            // Reset lastIndex after test() — regex with /g retains state between calls
             _autolinkRe.lastIndex = 0;
             const frag = document.createDocumentFragment();
             let last = 0, m;
             while ((m = _autolinkRe.exec(t)) !== null) {
                 if (m.index > last) frag.appendChild(document.createTextNode(t.slice(last, m.index)));
                 const a = document.createElement('a');
                 const href = m[0].match(/^https?:\/\/|^ftp:\/\//) ? m[0] : 'http://' + m[0];
                 a.href = href;
@@ -45,22 +50,26 @@ function autolinkText(html) {
             [...node.childNodes].forEach(walk);
         }
     };
     [...tmp.childNodes].forEach(walk);
     return tmp.innerHTML;
 }
 
 const _origMarkedParse = marked.parse.bind(marked);
+// Patch marked.parse to: (1) escape lone ~ so marked doesn't misinterpret as strikethrough,
+// (2) autolink bare URLs that marked leaves as plain text
 marked.parse = (src, ...args) => {
     const escaped = src.replace(/(?<!\~)\~(?!\~)/g, '\\~');
     const html = _origMarkedParse(escaped, ...args);
     return autolinkText(html);
 };
 
+// Global click handler: inline code in markdown acts as a copy button,
+// but if the content looks like a URL it opens in a new tab instead
 document.addEventListener('click', (e) => {
     if (e.target.closest('a')) return;
     const code = e.target.closest('.markdown-body code');
     if (!code || code.closest('pre')) return;
     const text = code.textContent.trim();
     if (/^(https?:\/\/|ftp:\/\/)/.test(text) || /^(\d{1,3}\.){3}\d{1,3}(:\d+)?(\/\S*)?$/.test(text)) {
         const url = /^https?:\/\/|^ftp:\/\//.test(text) ? text : 'http://' + text;
         window.open(url, '_blank', 'noopener');
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index e56fc9f7a..2a47c38a0 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -34,16 +34,17 @@ bot = None
 dp = Dispatcher()
 _manager = None
 _tasks = []
 DEEPGRAM_API_KEY = ""
 
 
 def save_config():
     CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
+    # Strip token before persisting — it's in .env, not on disk
     safe = {k: v for k, v in config.items() if k != "token"}
     CONFIG_PATH.write_text(json.dumps(safe, indent=2))
 
 
 def load_config():
     global config
     if CONFIG_PATH.exists():
         config = json.loads(CONFIG_PATH.read_text())
@@ -51,16 +52,17 @@ def load_config():
         config.pop("token", None)
         save_config()
 
 
 def _load_media_cache() -> dict[str, str]:
     if MEDIA_CACHE_PATH.exists():
         try:
             data = json.loads(MEDIA_CACHE_PATH.read_text())
+            # Drop entries whose files were deleted (cleanup rotation) — avoids dead references
             return {k: v for k, v in data.items() if Path(v).exists()}
         except Exception:
             pass
     return {}
 
 
 def _save_media_cache(cache: dict[str, str]):
     MEDIA_CACHE_PATH.write_text(json.dumps(cache))
@@ -87,19 +89,19 @@ _transcription_cache: dict[str, str] = _load_transcription_cache()
 
 def _media_name(prefix: str, ext: str, msg: types.Message) -> str:
     ts = msg.date.strftime("%Y%m%d_%H%M%S") if msg.date else str(msg.message_id)
     return f"{prefix}_{ts}_{msg.message_id}{ext}"
 
 
 UPLOADS_MAX_BYTES = int(os.getenv("UPLOADS_MAX_MB", "1024")) * 1024 * 1024
 
-# Юзернейм для @mention в сообщениях агента пользователю (его речь, тип "text" → 💬).
-# Пусто → без тэга. Тэгается ТОЛЬКО речь агента, НЕ внутренняя переписка агентов (📨 [from:]).
-# MVP: статичный ник из env. Динамическое определение «это обращение к юзеру» — в backlog.
+# @mention for agent-to-user speech (type "text" → 💬) so TG notifications fire on the owner.
+# NOT applied to inter-agent messages (📨 [from:]) — only direct user-facing responses.
+# Static username from env (MVP). Dynamic "is this addressed to the user" detection is in backlog.
 TG_USER_MENTION = os.getenv("TG_USER_MENTION", "").strip()
 
 
 def _cleanup_uploads():
     files = [f for f in UPLOADS_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
     total = sum(f.stat().st_size for f in files)
     if total <= UPLOADS_MAX_BYTES:
         return
@@ -108,16 +110,17 @@ def _cleanup_uploads():
         old = files.pop(0)
         total -= old.stat().st_size
         old.unlink()
         logger.info(f"Uploads cleanup: deleted {old.name}")
 
 
 async def _download_file(file_id: str, filename: str, unique_id: str = "") -> str | None:
     global _media_cache
+    # file_unique_id is stable across bots — cache hit avoids re-downloading the same TG file
     if unique_id and unique_id in _media_cache:
         cached = _media_cache[unique_id]
         if Path(cached).exists():
             return cached
         del _media_cache[unique_id]
     _cleanup_uploads()
     t0 = time.monotonic()
     try:
@@ -126,16 +129,18 @@ async def _download_file(file_id: str, filename: str, unique_id: str = "") -> st
         path = UPLOADS_DIR / name
         if path.exists():
             stem, suffix = path.stem, path.suffix
             i = 1
             while path.exists():
                 path = UPLOADS_DIR / f"{stem}_{i}{suffix}"
                 i += 1
         local_api = os.getenv("TG_LOCAL_API_URL", "")
+        # Local Bot API server provides absolute paths — copy directly instead of downloading
+        # over the network (~40ms vs ~2s for large files)
         if local_api and f.file_path and Path(f.file_path).is_absolute() and Path(f.file_path).exists():
             import shutil
             shutil.copy2(f.file_path, str(path))
             logger.info(f"download {filename}: local copy in {(time.monotonic()-t0)*1000:.0f}ms ({f.file_path})")
         else:
             await bot.download_file(f.file_path, str(path))
             logger.info(f"download {filename}: remote download in {(time.monotonic()-t0)*1000:.0f}ms")
         if unique_id:
@@ -230,16 +235,18 @@ async def _resolve_orch(msg: types.Message) -> tuple[str | None, object | None]:
         return None, None
     session = await _manager.ensure_loaded_any(orch_name)
     if not session:
         await msg.reply(f"❌ {orch_name} not found")
         return orch_name, None
     return orch_name, session
 
 
+# Messages arriving within DEBOUNCE_SEC of each other are batched into one agent send.
+# MEDIA_WAIT_MAX caps how long we stall for slow downloads before flushing without them.
 DEBOUNCE_SEC = 5
 MEDIA_WAIT_MAX = 30
 
 from enum import Enum
 from dataclasses import dataclass, field
 
 
 class _Phase(Enum):
@@ -261,16 +268,18 @@ _buffers: dict[str, _BufState] = {}
 
 
 def _get_buf(sid: str) -> _BufState:
     if sid not in _buffers:
         _buffers[sid] = _BufState()
     return _buffers[sid]
 
 
+# Cancel and restart the debounce timer each time a new message arrives —
+# only the final fire actually flushes the batch to the agent
 async def _arm_debounce(sid: str, buf: "_BufState"):
     if buf.debounce_task and not buf.debounce_task.done():
         buf.debounce_task.cancel()
     buf.phase = _Phase.COLLECTING
     buf.debounce_task = asyncio.create_task(_debounce_elapsed(sid))
 
 
 async def _debounce_elapsed(sid: str):
@@ -336,16 +345,18 @@ async def _send_to_agent(msg: types.Message, session, content: str):
     content = f"{_sender_tag(msg)}{content}"
     sid = session.id
     buf = _get_buf(sid)
     async with buf.lock:
         buf.entries.append((msg, content))
         await _arm_debounce(sid, buf)
 
 
+# Reserve a slot in the batch before the download completes —
+# slot index is returned so the download goroutine can fill it in via _resolve_media
 async def _register_media(msg: types.Message, session) -> tuple[str, int]:
     sid = session.id
     buf = _get_buf(sid)
     async with buf.lock:
         idx = len(buf.entries)
         buf.entries.append((msg, None))
         buf.pending_media += 1
         await _arm_debounce(sid, buf)
@@ -369,32 +380,35 @@ async def _resolve_media(sid: str, idx: int, content: str):
             buf.debounce_task = None
             flush_batch = batch
     if flush_batch is not None:
         await _flush_batch(sid, flush_batch)
 
 
 
 
+# TG Bot API entity offsets are in UTF-16 code units, not Python's character count or byte count
 def _utf16_len(s: str) -> int:
     return len(s.encode("utf-16-le")) // 2
 
 
 def _md_entities(text: str, base_offset: int = 0):
     from aiogram.types import MessageEntity as AioEntity
     try:
         converted, raw_ents = md_convert(text)
         ents = [AioEntity(**{**e.to_dict(), "offset": e.offset + base_offset}) for e in raw_ents] if raw_ents else []
         return converted, ents
     except Exception:
         return text, []
 
 
 
 
+# Edit an existing tool message to append the result inline —
+# avoids a separate message and keeps tool+result visually grouped in TG
 async def _edit_tool_with_result(msg, chat_id: int, tool_text: str, result_header: str, result_body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     nl = tool_text.index("\n")
     tool_header = tool_text[:nl]
     tool_body = tool_text[nl + 1:].rstrip()
     result_body = result_body.rstrip()
     conv_tool, tool_ents = _md_entities(tool_body, 0)
@@ -441,16 +455,18 @@ async def _edit_expandable(msg, chat_id: int, header: str, body: str):
             return
         try:
             await bot.edit_message_text(text, chat_id=chat_id, message_id=msg.message_id)
         except Exception as e2:
             if "message is not modified" not in str(e2).lower():
                 logger.warning(f"TG edit failed: {e2}")
 
 
+# Expandable blockquote wraps the body so long tool outputs are collapsed by default in TG.
+# Falls back to plain text if the Bot API version doesn't support EXPANDABLE_BLOCKQUOTE.
 async def _send_expandable(chat_id: int, thread_id: int, header: str, body: str):
     from aiogram.types import MessageEntity
     from aiogram.enums import MessageEntityType
     body = body.rstrip()
     conv_body, body_ents = _md_entities(body, _utf16_len(header) + 1)
     text = f"{header}\n{conv_body}"
     offset = _utf16_len(header) + 1
     length = _utf16_len(conv_body)
@@ -481,19 +497,22 @@ def _split_message(text: str, limit: int = TG_MSG_LIMIT) -> list[str]:
             cut = limit
         chunks.append(text[:cut])
         text = text[cut:].lstrip('\n')
     return chunks
 
 
 _flood_until: float = 0
 _last_send: float = 0
+# TG allows ~1 msg/sec per chat — enforce minimum interval to avoid flood errors
 _TG_MIN_INTERVAL = 1.0
 
 
+# Rate-limited send with flood control: waits out flood bans before retrying important messages.
+# Non-important messages are silently dropped after a flood to avoid queue buildup.
 async def _tg_send_safe(chat_id: int, text: str, thread_id: int = None,
                          entities=None, important: bool = False):
     global _flood_until, _last_send
     now = asyncio.get_event_loop().time()
     if _flood_until > now:
         await asyncio.sleep(_flood_until - now + 0.1)
         now = asyncio.get_event_loop().time()
     gap = now - _last_send
@@ -645,16 +664,18 @@ async def rename_orch_topic(old_name: str, new_name: str) -> dict:
         except Exception as e:
             logger.warning(f"Failed to rename TG topic {old_name} → {new_name}: {e}")
     return {"ok": True, "old_name": old_name, "new_name": new_name, "display": new_display, "thread_id": thread_id}
 
 
 _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
 
 
+# Prefer the top-level orchestrator (no parent) so send_file routes to the scope owner's topic,
+# not a sub-orchestrator. Falls back to any orchestrator if no top-level found.
 def _find_orch_for_scope(scope: str) -> str | None:
     from app.db import get_all_sessions
     top_level = None
     any_orch = None
     for s in get_all_sessions():
         if s.get("scope", "").rstrip("/") != scope.rstrip("/"):
             continue
         role = s.get("role", "worker")
@@ -777,20 +798,22 @@ async def _sync_all_topic_statuses():
         name = s.name
         if name not in config["topics"]:
             continue
         is_running = _any_running_in_scope(s.scope)
         _topic_status.pop(name, None)
         await _update_topic_status(name, is_running)
 
 
+# Custom emoji IDs in the target TG group — green dot for running, grey for idle
 _ICON_RUNNING = "5312016608254762256"
 _ICON_IDLE = "5350392020785437399"
 
 
+# Deduplicated topic icon updates — TG rate-limits edit_forum_topic, so skip if state unchanged
 async def _update_topic_status(orch_name: str, is_running: bool):
     if _topic_status.get(orch_name) == is_running:
         return
     _topic_status[orch_name] = is_running
     short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
     icon_id = _ICON_RUNNING if is_running else _ICON_IDLE
     thread_id = config["topics"].get(orch_name)
     if thread_id and bot:
@@ -1020,16 +1043,17 @@ async def stream_logs(orch_name: str, thread_id: int):
     session_id = None
     row = get_session_by_name(orch_name, scope)
     if row:
         session_id = row["id"]
     if not session_id:
         return
 
     from app.db import _conn
+    # Dedicated connection per stream loop — avoids sharing state with the request threads
     _poll_conn = _conn()
     logs = get_logs(session_id, after_id=0, conn=_poll_conn)
     last_id = logs[-1]["id"] if logs else 0
     _last_tool_msg = None
     _last_tool_text = ""
     _last_tool_name = ""   # track last tool for result image rendering
     _last_tool_raw = ""    # full raw content of last tool call
     _idle_ticks = 0
@@ -1096,16 +1120,18 @@ async def stream_logs(orch_name: str, thread_id: int):
                         _last_tool_text = f"{header}\n{tool_body}"
                         _last_tool_name = tool_name
                         _last_tool_raw = c
                         # Diff image for Edit/Write — if image sent, skip text expandable
                         _diff_sent = False
                         if tool_name in ("Edit", "Write"):
                             _diff_sent = await _send_diff_image(tool_name, c, config["group_id"], thread_id)
                         # Special formatting for send_message — render as pretty HTML
+                        # send_message tool: render as readable HTML instead of raw JSON expandable —
+                        # the recipient name and message body are the useful parts
                         if not _diff_sent and "send_message" in tool_name:
                             try:
                                 import json as _json
                                 colon_idx = c.index(":")
                                 sm_params = _json.loads(c[colon_idx + 1:].strip())
                                 sm_to = sm_params.get("to", "?")
                                 sm_msg = sm_params.get("message", "")
                                 import re as _re
@@ -1183,16 +1209,17 @@ async def stream_logs(orch_name: str, thread_id: int):
                             await _mirror_send(orch_name, converted, entities=aio_ents)
                         except Exception:
                             await _tg_send_safe(config["group_id"], chunk, thread_id,
                                                 important=is_important)
                             await _mirror_send(orch_name, chunk)
             except Exception as e:
                 logger.error(f"Stream error for {orch_name}: {e}")
                 _idle_ticks = 0
+            # Poll faster when active, slow down when idle to save CPU on long-running idle sessions
             await asyncio.sleep(2 if _idle_ticks < 3 else 5)
     finally:
         _poll_conn.close()
 
 
 @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
 async def handle_restart(msg: types.Message):
     if msg.chat.id != config.get("group_id"):
@@ -1395,16 +1422,18 @@ async def _deferred_startup():
         for name, thread_id in config["topics"].items():
             _tasks.append(asyncio.create_task(stream_logs(name, thread_id)))
         _tasks.append(asyncio.create_task(topic_sync_loop()))
         logger.info(f"TG deferred startup done | topics={len(config['topics'])}")
     except Exception as e:
         logger.error(f"TG deferred startup failed: {e}")
 
 
+# Health check for the local telegram-bot-api server — restarts it after 3 consecutive failures.
+# The local server sometimes hangs without crashing, so polling is the only detection.
 async def _bot_api_health_loop(local_api: str):
     import subprocess
     import aiohttp as _aio
     fails = 0
     while True:
         await asyncio.sleep(120)
         try:
             async with _aio.ClientSession() as s:
@@ -1418,16 +1447,17 @@ async def _bot_api_health_loop(local_api: str):
         logger.warning(f"Bot API health check failed ({fails}/3)")
         if fails >= 3:
             logger.error("Bot API unresponsive — restarting telegram-bot-api service")
             subprocess.run(["sudo", "systemctl", "restart", "telegram-bot-api"], capture_output=True)
             fails = 0
             await asyncio.sleep(30)
 
 
+# Polling loop with auto-restart — network blips or TG downtime shouldn't kill the bridge permanently
 async def _safe_polling():
     while True:
         try:
             logger.info("TG polling started")
             await dp.start_polling(bot)
         except Exception as e:
             logger.error(f"TG polling crashed: {e}, restarting in 10s")
             await asyncio.sleep(10)


## LATER FIX 1fe4ce1750 (6.8 days later): #82: #82: fix SSE race condition on agent switch
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

#82: #82: fix SSE race condition on agent switch


diff --git a/app/static/js/app.js b/app/static/js/app.js
index f86aef267..7e9507f34 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -154,27 +154,25 @@ function scheduleRefresh() {
         scheduleRefresh();
     }, 3000);
 }
 
 // SSE reconnects on error — server may restart mid-session, don't lose the log stream
 function connectSSE() {
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (!selectedAgent || !currentScope) return;
+    const targetAgent = selectedAgent;
     const lastId = chatLogs[selectedAgent]?.lastId || 0;
-    // On first connect (lastId=0), fetch the last 100 messages for initial display
     const limitParam = lastId === 0 ? '&limit=100' : '';
     const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
     eventSource = new EventSource(url);
     eventSource.onmessage = (event) => {
+        if (selectedAgent !== targetAgent) return;
         try {
             const l = JSON.parse(event.data);
-            // When the server echoes back a message we sent, replace our optimistic bubble
-            // with the confirmed version so timestamps and content match exactly.
-            // Dedup user messages: skip SSE echo if we sent it (optimistic bubble already visible)
             if (l.type === 'user_message' && localMessages.size > 0) {
                 const isLocal = localMessages.has(l.content) ||
                     [...localMessages].some(m => l.content.endsWith(m)) ||
                     [...localMessages].some(m => l.content.includes(m));
                 if (isLocal) {
                     for (const m of localMessages) {
                         if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                             localMessages.delete(m);
@@ -199,17 +197,17 @@ function connectSSE() {
                 window._scrollResetTimer = setTimeout(() => { scrollAfterLoad = false; }, 500);
             }
         } catch (e) { console.warn('SSE parse:', e); }
     };
     eventSource.onerror = () => {
         eventSource.close();
         eventSource = null;
         _onServerError();
-        setTimeout(connectSSE, 2000);
+        setTimeout(() => { if (selectedAgent === targetAgent) connectSSE(); }, 2000);
     };
 }
 
 function updateLoadMoreBtn() {
     const chat = $('#chat');
     const existing = $('#load-more-btn');
     const firstId = chatLogs[selectedAgent]?.firstId;
     if (!firstId || firstId <= 1) {
@@ -1078,16 +1076,17 @@ function selectOrchestrator(name, scope) {
     localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));
 
     onOrchestratorChange();
     renderOrchTabs(orchData);
 }
 
 async function onOrchestratorChange() {
     saveDraft();
+    if (eventSource) { eventSource.close(); eventSource = null; }
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
     chatLogs = {};
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
@@ -1104,31 +1103,31 @@ async function onOrchestratorChange() {
     updateInputState();
     restoreDraft();
     await refreshSessions(); connectSSE(); initFilePanel();
     if (_tasksTabActive) loadTasks();
     if (_jobsTabActive) loadJobs();
 }
 
 // === Agent Selection ===
-function selectAgent(name) {
+async function selectAgent(name) {
     saveDraft();
+    if (eventSource) { eventSource.close(); eventSource = null; }
     selectedAgent = name;
     streamBubble = null;
     streamContent = '';
     $('#chat').innerHTML = '';
     chatLogs[name] = { lastId: 0, firstId: null };
     scrollAfterLoad = true;
     updateInputState();
     restoreDraft();
     renderAgentList();
     fetchAgentContext(name);
-    refreshSessions();
-    // Brief delay before SSE connect — gives time for any in-flight send() to persist
-    setTimeout(() => { if (selectedAgent === name) connectSSE(); }, 300);
+    await refreshSessions();
+    connectSSE();
 }
 
 function updateInputState() {
     const input = $('#chat-input');
     const btn = $('#send-btn');
     if (!selectedAgent) {
         input.placeholder = 'Message...';
         input.disabled = false;