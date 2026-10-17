# Candidate cand-09

## ORIGIN commit 514a791b83 (2026-06-21): #84: #84: typewriter streaming animation
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index c22e99004..6c46534f1 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1088,18 +1088,20 @@ async function onOrchestratorChange() {
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
     chatLogs = {};
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
+    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
     streamBubble = null;
     streamContent = '';
+    streamPending = '';
     selectedAgent = opt?.dataset?.name || null;
     if (currentScope && selectedAgent) {
         localStorage.setItem('lastOrchScope', currentScope);
         localStorage.setItem('lastOrchName', selectedAgent);
     }
     $('#chat').innerHTML = '';
     scrollAfterLoad = true;
     updateAgentInfo(null);
@@ -1115,18 +1117,20 @@ async function selectAgent(name) {
     saveDraft();
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
     selectedAgent = name;
+    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
     streamBubble = null;
     streamContent = '';
+    streamPending = '';
     $('#chat').innerHTML = '';
     chatLogs[name] = { lastId: 0, firstId: null };
     scrollAfterLoad = true;
     updateInputState();
     restoreDraft();
     renderAgentList();
     fetchAgentContext(name);
     await refreshSessions();
@@ -1768,16 +1772,57 @@ function addCopyBtn(el, text) {
         btn.textContent = '✅';
         setTimeout(() => btn.textContent = '📋', 1500);
     });
     el.appendChild(btn);
 }
 
 let streamBubble = null;
 let streamContent = '';
+let streamPending = '';
+let _streamRafId = null;
+let _streamLastParse = 0;
+const _STREAM_BASE_CPS = 12;  // chars per frame at 60fps (~720 chars/sec)
+const _STREAM_PARSE_INTERVAL = 50;  // ms between marked.parse calls
+
+function _streamRenderTick() {
+    _streamRafId = null;
+    if (!streamBubble || !streamPending) return;
+    // Adaptive speed: if buffer is growing, accelerate to not fall behind
+    const chunkSize = Math.max(_STREAM_BASE_CPS, Math.floor(streamPending.length / 8));
+    const chunk = streamPending.slice(0, chunkSize);
+    streamPending = streamPending.slice(chunkSize);
+    streamContent += chunk;
+    const now = performance.now();
+    const sinceLastParse = now - _streamLastParse;
+    if (sinceLastParse >= _STREAM_PARSE_INTERVAL || !streamPending) {
+        _streamLastParse = now;
+        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
+    }
+    // Typing cursor — remove stale one before adding
+    const oldCur = streamBubble.querySelector('.typing-cursor');
+    if (oldCur) oldCur.remove();
+    const lastEl = streamBubble.querySelector(':scope > :last-child') || streamBubble;
+    const cur = document.createElement('span');
+    cur.className = 'typing-cursor';
+    cur.textContent = '▍';
+    lastEl.appendChild(cur);
+    const chat = $('#chat');
+    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
+    if (wasAtBottom) chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
+    if (streamPending) _streamRafId = requestAnimationFrame(_streamRenderTick);
+}
+
+function _streamFlush() {
+    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
+    if (streamPending) {
+        streamContent += streamPending;
+        streamPending = '';
+    }
+}
 
 function _renderJsonGrid(obj, container, maxDepth) {
     if (maxDepth === undefined) maxDepth = 2;
     const grid = document.createElement('div');
     grid.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px;align-items:baseline';
     const entries = Object.entries(obj);
     for (const [key, val] of entries) {
         if (key === 'system_prompt' || key === 'error_trace') continue;
@@ -2129,61 +2174,58 @@ function addChatEntry(type, content, ts, anchor) {
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(line);
         // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
         while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
         if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
-    // Stream events accumulate into one bubble that gets re-rendered on each chunk
+    // Stream events feed the typewriter buffer — RAF loop renders incrementally
     if (type === 'stream') {
         removeWaitingIndicator();
-        streamContent += content;
         if (!streamBubble) {
             streamBubble = document.createElement('div');
             streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
             streamBubble.style.position = 'relative';
             const agentColor = agentColors[selectedAgent];
             if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
             _insert(streamBubble);
+            _streamLastParse = 0;
         }
-        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
-        // Append typing cursor inside the last text node's parent
-        const lastEl = streamBubble.querySelector(':scope > :last-child') || streamBubble;
-        const cur = document.createElement('span');
-        cur.className = 'typing-cursor';
-        cur.textContent = '▍';
-        lastEl.appendChild(cur);
-        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
-        if (wasAtBottom) chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
+        streamPending += content;
+        if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
         return;
     }
 
-    // 'text' event signals streaming finished — the DB-persisted content is
-    // authoritative (partials may have been dropped/truncated), so replace the
-    // bubble body with it, then finalize with copy/timestamp.
+    // 'text' event signals streaming finished — flush typewriter buffer,
+    // replace with authoritative DB content, finalize with copy/timestamp.
     if (type === 'text' && streamBubble) {
+        _streamFlush();
         streamBubble.classList.remove('streaming');
         const finalText = content || streamContent;
         streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(finalText));
         addCopyBtn(streamBubble, finalText);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
+        streamPending = '';
         return;
     }
 
     // Any non-text log after a stream (e.g. tool call) also terminates the stream bubble
     if (streamBubble && type !== 'text') {
+        _streamFlush();
         streamBubble.classList.remove('streaming');
+        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
         addCopyBtn(streamBubble, streamContent);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
+        streamPending = '';
     }
 
     if (type === 'status') {
         const badge = document.createElement('div');
         badge.className = 'text-center text-xs py-1 text-slate-500 italic';
         badge.textContent = `⚡ ${content}`;
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;


## LATER FIX eeea9b7ae0 (1.9 days later): fix: insert non-stream messages before streaming bubble instead of finalizing it
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: insert non-stream messages before streaming bubble instead of finalizing it


diff --git a/app/static/js/app.js b/app/static/js/app.js
index 6c46534f1..4c2631f52 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2064,17 +2064,25 @@ function _findLastBefore(parent, selector, anchor) {
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 function addChatEntry(type, content, ts, anchor) {
     if (HIDE_THINKING && type === 'thinking') return;
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
-    const _insert = (el) => anchor ? chat.insertBefore(el, anchor) : chat.appendChild(el);
+    let _insertedBeforeStream = false;
+    const _insert = (el) => {
+        if (anchor) return chat.insertBefore(el, anchor);
+        if (streamBubble && streamBubble.parentNode === chat) {
+            _insertedBeforeStream = true;
+            return chat.insertBefore(el, streamBubble);
+        }
+        chat.appendChild(el);
+    };
 
     // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
     const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);
 
     if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
         const div = document.createElement('div');
         div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
         const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
@@ -2086,17 +2094,17 @@ function addChatEntry(type, content, ts, anchor) {
             div.appendChild(img);
         } else {
             div.textContent = '🖼 [Image]';
             div.style.color = '#64748b';
         }
         addTimestamp(div, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(div);
-        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     if (window.compactMode && (type === 'tool' || type === 'tool_result')) {
         if (type === 'tool_result') {
             const lastC = _findLastBefore(chat, '[data-compact-tool]', anchor);
             if (lastC && _isBase64Image) {
                 const resultSpan = lastC.querySelector('.compact-result');
@@ -2161,26 +2169,22 @@ function addChatEntry(type, content, ts, anchor) {
                         if (parsed.file_path) readShort = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || parsed.file_path;
                     } catch {}
                     resultSpan.textContent = '📖 ' + readShort;
                 }
                 lastC.dataset.resultContent = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
                 return;
             }
         }
-        if (streamBubble) {
-            streamBubble = null;
-            streamContent = '';
-        }
         const line = buildCompactToolLine(type, content, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(line);
         // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
         while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
-        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     // Stream events feed the typewriter buffer — RAF loop renders incrementally
     if (type === 'stream') {
         removeWaitingIndicator();
         if (!streamBubble) {
             streamBubble = document.createElement('div');
@@ -2206,36 +2210,24 @@ function addChatEntry(type, content, ts, anchor) {
         addCopyBtn(streamBubble, finalText);
         addTimestamp(streamBubble, ts);
         streamBubble = null;
         streamContent = '';
         streamPending = '';
         return;
     }
 
-    // Any non-text log after a stream (e.g. tool call) also terminates the stream bubble
-    if (streamBubble && type !== 'text') {
-        _streamFlush();
-        streamBubble.classList.remove('streaming');
-        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
-        addCopyBtn(streamBubble, streamContent);
-        addTimestamp(streamBubble, ts);
-        streamBubble = null;
-        streamContent = '';
-        streamPending = '';
-    }
-
     if (type === 'status') {
         const badge = document.createElement('div');
         badge.className = 'text-center text-xs py-1 text-slate-500 italic';
         badge.textContent = `⚡ ${content}`;
         addTimestamp(badge, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(badge);
-        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     if (type === 'subagent_start' || type === 'subagent_end' || type === 'subagent_progress') {
         const parts = content.split('|').map(p => p.trim());
         const meta = {};
         const textParts = [];
         for (const p of parts) {
@@ -2279,17 +2271,17 @@ function addChatEntry(type, content, ts, anchor) {
                         sumEl.style.maxHeight = _saExp ? 'none' : '40px';
                     });
                 }
             }
         }
         addTimestamp(el, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(el);
-        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     const div = document.createElement('div');
     div.className = `px-3 py-2 rounded-lg text-sm break-words ${
         type === 'user_message' ? 'chat-user ml-16' :
         type === 'tool' ? 'chat-tool' :
         type === 'tool_result' ? 'chat-tool-result' :
@@ -2951,17 +2943,17 @@ function addChatEntry(type, content, ts, anchor) {
                 placeholder.style.cssText = 'color:#64748b;margin-top:4px';
                 placeholder.textContent = '🖼 [Image result]';
                 target.appendChild(placeholder);
             }
             addTimestamp(target, ts);
             if (!lastTool) {
                 const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                 _insert(div);
-                if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
             }
             return;
         }
         const toolErrorMatch = content.match(/<tool_use_error>([\s\S]*?)<\/tool_use_error>/);
         if (toolErrorMatch) {
             const errMsg = toolErrorMatch[1].trim();
             const errDiv = document.createElement('div');
             errDiv.className = 'px-3 py-2 rounded-lg text-xs text-red-400 bg-red-950/30 border border-red-900/50';
@@ -2972,17 +2964,17 @@ function addChatEntry(type, content, ts, anchor) {
                 if (skeleton) skeleton.remove();
                 lastTool.appendChild(errDiv);
                 addTimestamp(lastTool, ts);
             } else {
                 div.appendChild(errDiv);
                 addTimestamp(div, ts);
                 const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                 _insert(div);
-                if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
             }
             return;
         }
         const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
         // Strip raw JSON link arrays from WebSearch results (shown as ugly JSON at top)
         const stripped = clean.replace(/^(Links:\s*\[.*?\}\]\s*\n?)+/gms, '');
         const escaped = stripped.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
         // Render markdown links [text](url) first, then bare URLs
@@ -3897,17 +3889,17 @@ function addChatEntry(type, content, ts, anchor) {
         if (wsStandalone) {
             const sep = document.createElement('div');
             sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
             sep.appendChild(wsStandalone);
             div.appendChild(sep);
             addTimestamp(div, ts);
             const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
             _insert(div);
-            if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+            if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
             return;
         }
 
         let _standaloneJson = null;
         try { _standaloneJson = JSON.parse(content); } catch {}
         if (_standaloneJson && typeof _standaloneJson === 'object' && !Array.isArray(_standaloneJson)) {
             let sData = _standaloneJson;
             if (sData.result !== undefined && Object.keys(sData).length === 1) {
@@ -3918,17 +3910,17 @@ function addChatEntry(type, content, ts, anchor) {
             if (sData && typeof sData === 'object' && !Array.isArray(sData)) {
                 const gridWrap = document.createElement('div');
                 gridWrap.style.cssText = 'margin-top:4px';
                 _renderJsonGrid(sData, gridWrap);
                 div.appendChild(gridWrap);
                 addTimestamp(div, ts);
                 const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                 _insert(div);
-                if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
                 return;
             }
         }
         const resultBody = document.createElement('div');
         resultBody.style.whiteSpace = 'pre-wrap';
         resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
         div.appendChild(resultBody);
         if (full) {
@@ -3955,17 +3947,17 @@ function addChatEntry(type, content, ts, anchor) {
         renderImages(div, content);
     }
 
     addCopyBtn(div, content);
     addTimestamp(div, ts);
     const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
     _insert(div);
     while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
-    if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
+    if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
 }
 
 
 const FILE_ICONS = {
     py: '🐍', js: '📜', ts: '📜', json: '📋', md: '📝', html: '🌐', css: '🎨',
     txt: '📄', yml: '⚙️', yaml: '⚙️', toml: '⚙️', sh: '🖥', sql: '🗃',
     png: '🖼', jpg: '🖼', svg: '🖼', gif: '🖼',
 };