# Candidate cand-17

## ORIGIN commit 3a3757ee69 (2026-07-03): feat: visible rate-limit banner with countdown timer
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 760752b90..930da486d 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2219,16 +2219,17 @@ function addChatEntry(type, content, ts, anchor, payload) {
         while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     // Stream events feed the typewriter buffer — RAF loop renders incrementally
     if (type === 'stream') {
         removeWaitingIndicator();
+        if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
         if (!streamBubble) {
             streamBubble = document.createElement('div');
             streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
             streamBubble.style.position = 'relative';
             const agentColor = agentColors[selectedAgent];
             if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
             _insert(streamBubble);
             _streamLastParse = 0;
@@ -2249,19 +2250,27 @@ function addChatEntry(type, content, ts, anchor, payload) {
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
         streamPending = '';
         return;
     }
 
     if (type === 'status') {
+        const rl = _parseRateLimitStatus(content);
         const badge = document.createElement('div');
-        badge.className = 'text-center text-xs py-1 text-slate-500 italic';
-        badge.textContent = `⚡ ${content}`;
+        if (rl) {
+            // Rate limit: trigger the global banner (live logs only, not history replay)
+            if (!anchor) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
+            badge.className = 'text-center text-xs py-1 text-amber-400 italic';
+            badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
+        } else {
+            badge.className = 'text-center text-xs py-1 text-slate-500 italic';
+            badge.textContent = `⚡ ${content}`;
+        }
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(badge);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     if (type === 'subagent_start' || type === 'subagent_end' || type === 'subagent_progress') {
@@ -4003,17 +4012,24 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 sExpanded = !sExpanded;
                 resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(sExpanded ? full : preview, {ADD_ATTR: ['target']});
                 sHint.textContent = sExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
             };
             div.style.cursor = 'pointer';
             div.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleStandalone(); });
         }
     }
-    else if (type === 'error') { div.textContent = content; }
+    else if (type === 'error') {
+        if (/rate.?limit/i.test(content)) {
+            div.textContent = '⏳ Rate limit — Anthropic временно ограничил запросы (это НЕ лимит твоей подписки). Orchestra автоматически повторит.';
+            div.className = div.className.replace('text-red-400', 'text-amber-400');
+        } else {
+            div.textContent = content;
+        }
+    }
     else {
         div.innerHTML = DOMPurify.sanitize(marked.parse(content));
         const agentColor = agentColors[selectedAgent];
         if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
         renderImages(div, content);
     }
 
     addCopyBtn(div, content);
@@ -4315,16 +4331,53 @@ async function _pollReconnect() {
 }
 
 // Two consecutive failures before showing overlay — one transient error shouldn't panic the UI
 function _onServerError() {
     _rebootFails++;
     if (_rebootFails >= 2) _showRebootOverlay();
 }
 
+// === Rate Limit Banner (Anthropic server-side rate_limit, not subscription) ===
+let _rateLimitTimer = null;
+let _rateLimitAgent = null;
+
+function _showRateLimitBanner(agentName, retryNum, maxRetries, delaySec) {
+    const banner = document.getElementById('rate-limit-banner');
+    if (!banner) return;
+    _rateLimitAgent = agentName;
+    let remaining = delaySec;
+    banner.classList.remove('hidden');
+    banner.classList.add('flex');
+    const render = () => {
+        banner.innerHTML = `⏳ <b>Rate limit (сервер Anthropic)</b> — ${escHtml(agentName)}: повтор ${retryNum}/${maxRetries} через <b class="text-amber-100">${remaining}с</b> <span class="text-amber-400/70">· это НЕ лимит твоей подписки</span>`;
+    };
+    render();
+    if (_rateLimitTimer) clearInterval(_rateLimitTimer);
+    _rateLimitTimer = setInterval(() => {
+        remaining--;
+        if (remaining <= 0) { render(); _hideRateLimitBanner(); return; }
+        render();
+    }, 1000);
+}
+
+function _hideRateLimitBanner() {
+    const banner = document.getElementById('rate-limit-banner');
+    if (_rateLimitTimer) { clearInterval(_rateLimitTimer); _rateLimitTimer = null; }
+    _rateLimitAgent = null;
+    if (banner) { banner.classList.add('hidden'); banner.classList.remove('flex'); banner.innerHTML = ''; }
+}
+
+// Parse "rate limited — retry N/M in Xs" from status log content
+function _parseRateLimitStatus(content) {
+    const m = content.match(/rate limited\s*—\s*retry\s*(\d+)\/(\d+)\s*in\s*(\d+)s/i);
+    if (!m) return null;
+    return { retry: +m[1], max: +m[2], delay: +m[3] };
+}
+
 function _onServerOk() {
     _rebootFails = 0;
 }
 
 function initHeartbeat() {
     setInterval(async () => {
         try {
             const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
@@ -4940,18 +4993,19 @@ async function loadProxyList() {
         const proxies = data.proxies || [];
         if (!proxies.length) {
             list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No proxies configured.<br>Set PROXY_LIST in .env</div>';
             return;
         }
         for (const p of proxies) {
             const el = document.createElement('div');
             el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
-            const status = p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
-            const statusTitle = p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
+            const isRateLimited = p.ok === false && /429|rate.?limit/i.test(String(p.error || ''));
+            const status = isRateLimited ? '⏳' : p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
+            const statusTitle = isRateLimited ? 'Rate limit (429) — проверь позже' : p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
             const flag = p.flag || '🏳️';
             const location = p.city ? `${p.city}, ${p.country || ''}` : p.country || '';
             el.innerHTML = `
                 <span class="text-sm" title="${statusTitle}">${status}</span>
                 <div class="flex-1 min-w-0">
                     <div class="flex items-center gap-1.5">
                         <span class="text-sm">${flag}</span>
                         <span class="proxy-name text-xs font-medium text-white truncate">${escHtml(p.name)}</span>
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 4df08c078..4e893099a 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -9,16 +9,17 @@
     <script src="/static/css/vendor/purify.min.js"></script>
     <script src="/static/css/vendor/diff_match_patch.js"></script>
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
     <script src="/static/css/vendor/highlight.min.js"></script>
     <link rel="stylesheet" href="/static/css/vendor/highlight-github-dark.min.css">
     <link rel="stylesheet" href="/static/css/style.css">
 </head>
 <body class="h-screen flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}" data-client-name="{{ client_name }}">
+    <div id="rate-limit-banner" class="hidden items-center justify-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/40 text-amber-200 text-xs"></div>
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
             <h1 class="text-lg font-bold tracking-tight shrink-0">🎼</h1>
             <div id="orch-tabs" class="flex items-center gap-1.5 overflow-x-auto no-scrollbar"></div>
             <select id="orch-picker" class="hidden"></select>
             <button id="new-orch-btn" class="px-2.5 py-1.5 bg-slate-800/50 hover:bg-slate-700 border border-dashed border-slate-700 rounded-full text-xs transition-colors shrink-0" title="New orchestrator">+</button>
             <button id="hidden-tabs-btn" class="px-2 py-1.5 hover:bg-slate-700 rounded-full text-xs transition-colors text-slate-500 hover:text-slate-300 shrink-0 hidden" title="Show hidden tabs">👁</button>


## LATER FIX 710a21be76 (4.2 days later): Fix: rate-limit banner persists on agent switch + triggers on history replay
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

Fix: rate-limit banner persists on agent switch + triggers on history replay

1. Clear banner on selectAgent (was leaking from previous agent)
2. Skip banner during initial SSE batch (scrollAfterLoad=true)


diff --git a/app/static/js/app.js b/app/static/js/app.js
index 21e4f89b3..cc4dd8493 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1129,16 +1129,17 @@ async function selectAgent(name) {
     saveDraft();
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
     selectedAgent = name;
+    _hideRateLimitBanner();
     if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
     streamBubble = null;
     streamContent = '';
     streamPending = '';
     $('#chat').innerHTML = '';
     chatLogs[name] = { lastId: 0, firstId: null, initialCount: 0 };
     scrollAfterLoad = true;
     updateInputState();
@@ -2268,18 +2269,18 @@ function addChatEntry(type, content, ts, anchor, payload) {
         streamPending = '';
         return;
     }
 
     if (type === 'status') {
         const rl = _parseRateLimitStatus(content);
         const badge = document.createElement('div');
         if (rl) {
-            // Rate limit: trigger the global banner (live logs only, not history replay)
-            if (!anchor) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
+            // Rate limit: trigger the global banner (live logs only, not history/initial replay)
+            if (!anchor && !scrollAfterLoad) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
             badge.className = 'text-center text-xs py-1 text-amber-400 italic';
             badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
         } else {
             badge.className = 'text-center text-xs py-1 text-slate-500 italic';
             badge.textContent = `⚡ ${content}`;
         }
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;