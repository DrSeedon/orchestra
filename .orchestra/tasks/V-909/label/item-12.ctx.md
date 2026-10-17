# Context for item-12

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 03b9150fb..25c1371f7 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -369,77 +369,82 @@ async function restartCli() {
 async function openPromptModal() {
     if (!selectedAgent || !currentScope) return;
     const modal = $('#prompt-modal');
     const body = $('#prompt-modal-body');
     $('#prompt-modal-name').textContent = selectedAgent;
     body.innerHTML = '<span class="text-slate-500 text-xs">Loading...</span>';
     modal.classList.remove('hidden');
     modal.classList.add('flex');
     try {
         const blocks = await api(`/api/sessions/${selectedAgent}/prompt-blocks?scope=${encodeURIComponent(currentScope)}`);
         if (!Array.isArray(blocks) || blocks.length === 0) {
             body.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
             return;
         }
         _renderPromptBlocks(body, blocks);
     } catch (e) {
         body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
     }
 }
 
-function _renderPromptBlocks(container, blocks) {
+function _renderPromptBlocks(container, blocks, expandAll = false) {
     const TYPE_COLORS = { static: '#3b82f6', dynamic: '#f59e0b', skill: '#22c55e' };
     const TYPE_LABELS = { static: 'file', dynamic: 'dynamic', skill: 'skill' };
     const staticN = blocks.filter(b => b.type === 'static').length;
     const dynN = blocks.filter(b => b.type === 'dynamic').length;
     const totalChars = blocks.reduce((s, b) => s + (b.size || 0), 0);
     const totalTokens = Math.round(totalChars / 4);
 
     let html = `<div class="pb-summary">
         <span class="pb-stat"><b>${blocks.length}</b> blocks</span>
         <span class="pb-stat" style="color:#3b82f6"><b>${staticN}</b> static</span>
         <span class="pb-stat" style="color:#f59e0b"><b>${dynN}</b> dynamic</span>
         <span class="pb-stat"><b>~${totalTokens >= 1000 ? (totalTokens/1000).toFixed(1)+'k' : totalTokens}</b> tokens</span>
     </div>`;
 
     blocks.forEach((b, i) => {
         const color = TYPE_COLORS[b.type] || '#64748b';
         const label = TYPE_LABELS[b.type] || b.type;
         const tokens = Math.round((b.size || 0) / 4);
         const tokStr = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
-        html += `<div class="pb-block" style="border-left-color:${color}" data-pb-idx="${i}">
+        const openClass = expandAll ? ' pb-open' : '';
+        html += `<div class="pb-block${openClass}" style="border-left-color:${color}" data-pb-idx="${i}">
             <div class="pb-header" onclick="this.parentElement.classList.toggle('pb-open')">
                 <span class="pb-chevron">▸</span>
                 <span class="pb-tag" style="background:${color}22;color:${color}">${label}</span>
                 <span class="pb-title">${escHtml(b.title)}</span>
                 <span class="pb-meta">${tokStr} tok</span>
                 ${b.source ? `<span class="pb-source">${escHtml(b.source)}</span>` : ''}
             </div>
             <div class="pb-body"></div>
         </div>`;
     });
     container.innerHTML = html;
 
     container.querySelectorAll('.pb-block').forEach((el, i) => {
         const b = blocks[i];
+        const bodyEl = el.querySelector('.pb-body');
+        if (expandAll && b.content) {
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
     });
 }
 
 function openImageLightbox(src) {
     const overlay = document.createElement('div');
     overlay.className = 'img-lightbox';
     const img = document.createElement('img');
     img.src = src;
     img.style.cssText = 'max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.6);object-fit:contain';
     overlay.appendChild(img);
     document.body.appendChild(overlay);
     overlay.addEventListener('click', (e) => { if (e.target !== img) overlay.remove(); });
     img.addEventListener('click', (e) => { e.stopPropagation(); window.open(src, '_blank'); });
     const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
     document.addEventListener('keydown', onKey);
@@ -1166,40 +1171,42 @@ async function _showModelPicker(agentName, currentModel, anchor) {
         dd.appendChild(item);
     }
     document.body.appendChild(dd);
     const close = (e) => { if (!dd.contains(e.target) && e.target !== anchor) { dd.remove(); document.removeEventListener('click', close); } };
     setTimeout(() => document.addEventListener('click', close), 0);
 }
 
 function updateAgentInfo(session) {
     if (!session) {
         $('#ai-name').textContent = '-';
         $('#ai-status').textContent = '';
         $('#ai-model').textContent = '-';
         $('#ai-role').textContent = '-';
         $('#ai-cost').textContent = '-';
         $('#ai-branch').textContent = '-';
         $('#ai-scope').textContent = '-';
         setContextDisplay('-');
         $('#view-prompt-btn').classList.add('hidden');
         $('#compact-btn').classList.add('hidden');
         $('#restart-cli-btn').classList.add('hidden');
+        const pp = $('#agent-prompt-preview');
+        if (pp) { pp.classList.add('hidden'); _lastPromptAgent = ''; }
         return;
     }
     $('#view-prompt-btn').classList.remove('hidden');
     $('#compact-btn').classList.remove('hidden');
     $('#restart-cli-btn').classList.remove('hidden');
     const isRunning = session.status === 'running';
     $('#compact-btn').disabled = isRunning;
     $('#compact-btn').title = isRunning ? 'Wait for idle' : 'Compact context';
     $('#ai-name').textContent = session.name;
     const st = $('#ai-status');
     st.textContent = `● ${session.status}`;
     st.className = `text-xs font-mono status-${session.status}`;
     const modelEl = $('#ai-model');
     modelEl.textContent = session.model || '-';
     let changeBtn = $('#ai-model-change');
     if (!changeBtn) {
         changeBtn = document.createElement('span');
         changeBtn.id = 'ai-model-change';
         changeBtn.style.cssText = 'cursor:pointer;font-size:10px;margin-left:4px;color:#475569;transition:color 0.15s';
         changeBtn.textContent = '⇄';
@@ -1229,40 +1236,62 @@ function updateAgentInfo(session) {
             progLabel = document.createElement('span'); progLabel.id = 'ai-progress-label'; progLabel.className = 'text-slate-500 hidden'; progLabel.textContent = 'Progress';
             progEl = document.createElement('span'); progEl.id = 'ai-progress'; progEl.className = 'text-indigo-400 text-xs truncate hidden'; progEl.style.maxWidth = '180px';
             grid.append(progLabel, progEl);
         }
     }
     if (progEl && progLabel) {
         const pp = session.progress_pct || 0;
         if (pp > 0) {
             const ps = session.progress_status ? ` — ${session.progress_status}` : '';
             progEl.textContent = `${pp}%${ps}`; progEl.title = `${pp}%${ps}`;
             progEl.classList.remove('hidden'); progLabel.classList.remove('hidden');
         } else { progEl.classList.add('hidden'); progLabel.classList.add('hidden'); }
     }
     const ctxKey = `${currentScope}:${session.name}`;
     if (contextCache[ctxKey]) {
         setContextDisplay(contextCache[ctxKey]);
     } else {
         setContextDisplay('...');
     }
     fetchAgentContext(session.name);
+    _loadInlinePrompt(session.name);
+}
+
+let _lastPromptAgent = '';
+async function _loadInlinePrompt(agentName) {
+    const preview = $('#agent-prompt-preview');
+    const content = $('#agent-prompt-content');
+    if (!preview || !content) return;
+    if (_lastPromptAgent === agentName && content.children.length > 1) return;
+    _lastPromptAgent = agentName;
+    content.innerHTML = '<span class="text-slate-500 text-xs">Loading prompt...</span>';
+    preview.classList.remove('hidden');
+    try {
+        const blocks = await api(`/api/sessions/${agentName}/prompt-blocks?scope=${encodeURIComponent(currentScope)}`);
+        if (!Array.isArray(blocks) || blocks.length === 0) {
+            content.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
+            return;
+        }
+        _renderPromptBlocks(content, blocks, true);
+    } catch (e) {
+        content.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
+    }
 }
 
 function setContextDisplay(text) {
     let ctxEl = $('#ai-context');
     if (!ctxEl) {
         const grid = $('#agent-info .grid');
         const label = document.createElement('span');
         label.className = 'text-slate-500';
         label.textContent = 'Context';
         ctxEl = document.createElement('span');
         ctxEl.id = 'ai-context';
         ctxEl.className = 'text-amber-400';
         grid.append(label, ctxEl);
     }
     ctxEl.textContent = text;
 }
 
 function formatContext(ctx) {
     const pct = Math.round(ctx.percentage || 0);
     const total = ctx.total_tokens || 0;
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 68d992f2e..495e3da8a 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -187,40 +187,47 @@
             <div id="agent-info" class="px-4 py-3 border-b border-slate-800/50 space-y-2">
                 <div class="flex items-center justify-between gap-2">
                     <span id="ai-name" class="font-semibold text-sm truncate min-w-0"></span>
                     <div class="flex items-center gap-2 shrink-0">
                         <button id="compact-btn" class="text-slate-500 hover:text-amber-300 text-xs hidden" title="Compact context">🗜</button>
                         <button id="restart-cli-btn" class="text-slate-500 hover:text-green-300 text-xs hidden" title="Restart CLI">♻️</button>
                         <button id="view-prompt-btn" class="text-slate-500 hover:text-indigo-300 text-xs hidden" title="View system prompt">📜</button>
                         <span id="ai-status" class="text-xs font-mono"></span>
                     </div>
                 </div>
                 <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                     <span class="text-slate-500">Model</span><span id="ai-model" class="text-slate-300 break-all"></span>
                     <span class="text-slate-500">Role</span><span id="ai-role" class="text-purple-400 break-all"></span>
                     <span class="text-slate-500">Cost</span><span id="ai-cost" class="text-green-400"></span>
                     <span class="text-slate-500">Branch</span><span id="ai-branch" class="text-indigo-400 break-all font-mono"></span>
                     <span class="text-slate-500">Scope</span><span id="ai-scope" class="text-slate-400 text-xs break-all"></span>
                     <span id="ai-desc-label" class="text-slate-500 hidden">Desc</span><span id="ai-desc" class="text-slate-400 text-xs truncate hidden" style="max-width:180px"></span>
                 </div>
             </div>
 
+            <!-- Agent Prompt Preview (inline, no modal needed) -->
+            <div id="agent-prompt-preview" class="border-b border-slate-800/50 overflow-y-auto hidden" style="max-height:50vh">
+                <div class="px-3 py-2">
+                    <div id="agent-prompt-content" class="text-xs"></div>
+                </div>
+            </div>
+
             <!-- Agent List -->
             <div class="flex-1 overflow-y-auto">
                 <div id="agent-list" class="p-2 space-y-1"></div>
             </div>
         </div>
     </div>
 
     <!-- File Preview Modal -->
     <div id="file-preview-modal" class="fixed inset-0 z-50 items-center justify-center hidden" style="pointer-events:none">
         <div class="glass glow rounded-xl flex flex-col w-[700px] max-w-[90vw] max-h-[80vh]" style="pointer-events:auto;box-shadow:0 8px 32px rgba(0,0,0,0.6)">
             <div class="flex items-center justify-between px-4 py-3 border-b border-slate-800/50 shrink-0">
                 <span id="file-preview-path" class="text-xs font-mono text-slate-400 truncate max-w-[70%]"></span>
                 <div class="flex items-center gap-2">
                     <a id="file-preview-download" href="#" download class="hidden text-xs px-2 py-1 rounded bg-emerald-600/30 text-emerald-300 hover:bg-emerald-600/50 transition-colors" title="Download file">⬇ Download</a>
                     <a id="file-preview-open" href="#" target="_blank" class="hidden text-xs px-2 py-1 rounded bg-indigo-600/30 text-indigo-300 hover:bg-indigo-600/50 transition-colors" title="Open in browser">🌐 Open</a>
                     <button id="file-preview-close" class="text-slate-500 hover:text-white text-lg">✕</button>
                 </div>
             </div>
             <pre id="file-preview-content" class="flex-1 overflow-auto text-xs p-4 whitespace-pre-wrap break-all text-slate-300" style="overflow-x:hidden;word-wrap:break-word"></pre>
         </div>


## Later history of the touched files on main (after this commit)

237 later commits touch these paths; the first 40 (oldest first):
63bfa4e4c 2026-06-13 Revert "#90: dashboard UX — expand all sections, show role/model/prompt upfront"
87892e50f 2026-06-13 #90: revert inline prompt — keep compact right panel, prompt in modal only
712fd6cf4 2026-06-13 fix: filter model dropdown to Claude/GPT only — hide proxy-injected third-party models
f1a5ba6e4 2026-06-13 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict
4dd1e12f6 2026-06-13 remove enterprise features from open source: block-creation, auth-gated UI, auto-bootstrap
a755646c6 2026-06-13 #91: client info page + proxy-only models + connection indicator
cbe4f00b0 2026-06-13 Revert "#91: client info page + proxy-only models + connection indicator"
9d7ba03ed 2026-06-13 prompt modal: all blocks open by default, tag-specific colors (role=green, rules=red, module=blue, dynamic=yellow)
79cc3fa0f 2026-06-13 #91: #91: client info page + proxy-only models + connection indicator
d0bf04778 2026-06-13 #92: enterprise cleanup — hide dev UI, client info modal
920f7d9f3 2026-06-13 fix: model dropdown sync + resolve_model fallback to first available
b196f3e6f 2026-06-13 fix: model picker click — stopPropagation + reload sessions after change
e9f76b901 2026-06-13 #93: enterprise production hardening — skip tunnel/yougile, fix usage/proxy JS
f38cd69c7 2026-06-13 #94: auto-retry proxy + client modal improvements + refresh button
12b7b6594 2026-06-13 fix: dynamic cost precision — show $0.001 not $0.00 for cheap models
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
1f5001124 2026-06-29 #86: #86: real per-day cost analytics from turn logs
18d806139 2026-07-01 #4: #proxy-fix: force stable id='direct' for direct proxy
6ce9c9c5c 2026-07-01 proxy: replace hot-switch with .env write + restart flow
1473e3745 2026-07-01 #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 63bfa4e4c Revert "#90: dashboard UX — expand all sections, show role/model/prompt upfront"

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 25c1371f7..03b9150fb 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -384,11 +384,11 @@ async function openPromptModal() {
     } catch (e) {
         body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
     }
 }
 
-function _renderPromptBlocks(container, blocks, expandAll = false) {
+function _renderPromptBlocks(container, blocks) {
     const TYPE_COLORS = { static: '#3b82f6', dynamic: '#f59e0b', skill: '#22c55e' };
     const TYPE_LABELS = { static: 'file', dynamic: 'dynamic', skill: 'skill' };
     const staticN = blocks.filter(b => b.type === 'static').length;
     const dynN = blocks.filter(b => b.type === 'dynamic').length;
     const totalChars = blocks.reduce((s, b) => s + (b.size || 0), 0);
@@ -404,12 +404,11 @@ function _renderPromptBlocks(container, blocks, expandAll = false) {
     blocks.forEach((b, i) => {
         const color = TYPE_COLORS[b.type] || '#64748b';
         const label = TYPE_LABELS[b.type] || b.type;
         const tokens = Math.round((b.size || 0) / 4);
         const tokStr = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
-        const openClass = expandAll ? ' pb-open' : '';
-        html += `<div class="pb-block${openClass}" style="border-left-color:${color}" data-pb-idx="${i}">
+        html += `<div class="pb-block" style="border-left-color:${color}" data-pb-idx="${i}">
             <div class="pb-header" onclick="this.parentElement.classList.toggle('pb-open')">
                 <span class="pb-chevron">▸</span>
                 <span class="pb-tag" style="background:${color}22;color:${color}">${label}</span>
                 <span class="pb-title">${escHtml(b.title)}</span>
                 <span class="pb-meta">${tokStr} tok</span>
@@ -420,16 +419,12 @@ function _renderPromptBlocks(container, blocks, expandAll = false) {
     });
     container.innerHTML = html;
 
     container.querySelectorAll('.pb-block').forEach((el, i) => {
         const b = blocks[i];
-        const bodyEl = el.querySelector('.pb-body');
-        if (expandAll && b.content) {
-            bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
-            bodyEl.dataset.loaded = '1';
-        }
         el.querySelector('.pb-header').addEventListener('click', () => {
+            const bodyEl = el.querySelector('.pb-body');
             if (!bodyEl.dataset.loaded && b.content) {
                 bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
                 bodyEl.dataset.loaded = '1';
             }
         });
@@ -1186,12 +1181,10 @@ function updateAgentInfo(session) {
         $('#ai-scope').textContent = '-';
         setContextDisplay('-');
         $('#view-prompt-btn').classList.add('hidden');
         $('#compact-btn').classList.add('hidden');
         $('#restart-cli-btn').classList.add('hidden');
-        const pp = $('#agent-prompt-preview');
-        if (pp) { pp.classList.add('hidden'); _lastPromptAgent = ''; }
         return;
     }
     $('#view-prompt-btn').classList.remove('hidden');
     $('#compact-btn').classList.remove('hidden');
     $('#restart-cli-btn').classList.remove('hidden');
@@ -1251,32 +1244,10 @@ function updateAgentInfo(session) {
         setContextDisplay(contextCache[ctxKey]);
     } else {
         setContextDisplay('...');
     }
     fetchAgentContext(session.name);
-    _loadInlinePrompt(session.name);
-}
-
-let _lastPromptAgent = '';
-async function _loadInlinePrompt(agentName) {
-    const preview = $('#agent-prompt-preview');
-    const content = $('#agent-prompt-content');
-    if (!preview || !content) return;
-    if (_lastPromptAgent === agentName && content.children.length > 1) return;
-    _lastPromptAgent = agentName;
-    content.innerHTML = '<span class="text-slate-500 text-xs">Loading prompt...</span>';
-    preview.classList.remove('hidden');
-    try {
-        const blocks = await api(`/api/sessions/${agentName}/prompt-blocks?scope=${encodeURIComponent(currentScope)}`);
-        if (!Array.isArray(blocks) || blocks.length === 0) {
-            content.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
-            return;
-        }
-        _renderPromptBlocks(content, blocks, true);
-    } catch (e) {
-        content.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
-    }
 }
 
 function setContextDisplay(text) {
     let ctxEl = $('#ai-context');
     if (!ctxEl) {
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 495e3da8a..68d992f2e 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -202,17 +202,10 @@
                     <span class="text-slate-500">Scope</span><span id="ai-scope" class="text-slate-400 text-xs break-all"></span>
                     <span id="ai-desc-label" class="text-slate-500 hidden">Desc</span><span id="ai-desc" class="text-slate-400 text-xs truncate hidden" style="max-width:180px"></span>
                 </div>
             </div>
 
-            <!-- Agent Prompt Preview (inline, no modal needed) -->
-            <div id="agent-prompt-preview" class="border-b border-slate-800/50 overflow-y-auto hidden" style="max-height:50vh">
-                <div class="px-3 py-2">
-                    <div id="agent-prompt-content" class="text-xs"></div>
-                </div>
-            </div>
-
             <!-- Agent List -->
             <div class="flex-1 overflow-y-auto">
                 <div id="agent-list" class="p-2 space-y-1"></div>
             </div>
         </div>
### 87892e50f #90: revert inline prompt — keep compact right panel, prompt in modal only

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 03b9150fb..8da188b14 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -378,11 +378,11 @@ async function openPromptModal() {
         const blocks = await api(`/api/sessions/${selectedAgent}/prompt-blocks?scope=${encodeURIComponent(currentScope)}`);
         if (!Array.isArray(blocks) || blocks.length === 0) {
             body.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
             return;
         }
-        _renderPromptBlocks(body, blocks);
+        _renderPromptBlocks(body, blocks, true);
     } catch (e) {
         body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
     }
 }
 
### 712fd6cf4 fix: filter model dropdown to Claude/GPT only — hide proxy-injected third-party models

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 8da188b14..ca21288ca 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -252,11 +252,13 @@ async function loadMoreLogs() {
 async function loadModels() {
     try {
         const models = await api('/api/models');
         const select = $('#orch-model');
         select.innerHTML = '';
-        for (const m of models) {
+        // Only show Claude and GPT models — proxy may inject third-party models
+        const filtered = models.filter(m => m.id.startsWith('claude-') || m.id.startsWith('gpt-'));
+        for (const m of filtered) {
             const opt = document.createElement('option');
             opt.value = m.id;
             opt.textContent = `${m.name} (${m.id})`;
             select.appendChild(opt);
         }
### f1a5ba6e4 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict

diff --git a/app/static/js/app.js b/app/static/js/app.js
index ca21288ca..8da188b14 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -252,13 +252,11 @@ async function loadMoreLogs() {
 async function loadModels() {
     try {
         const models = await api('/api/models');
         const select = $('#orch-model');
         select.innerHTML = '';
-        // Only show Claude and GPT models — proxy may inject third-party models
-        const filtered = models.filter(m => m.id.startsWith('claude-') || m.id.startsWith('gpt-'));
-        for (const m of filtered) {
+        for (const m of models) {
             const opt = document.createElement('option');
             opt.value = m.id;
             opt.textContent = `${m.name} (${m.id})`;
             select.appendChild(opt);
         }
### 4dd1e12f6 remove enterprise features from open source: block-creation, auth-gated UI, auto-bootstrap

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 8da188b14..dce523d62 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -123,14 +123,10 @@ document.addEventListener('DOMContentLoaded', () => {
         openFolderBtn.addEventListener('click', () => {
             if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
         });
     }
     loadModels();
-    if (document.body.dataset.authEnabled === 'true') {
-        document.getElementById('new-orch-btn')?.remove();
-        document.getElementById('new-orch-modal')?.remove();
-    }
     loadOrchestrators();
     scheduleRefresh();
     initFilePreviewModal();
     initUsageBar();
     initHeartbeat();
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 68d992f2e..c7dc8b35c 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -10,11 +10,11 @@
     <script src="/static/css/vendor/diff_match_patch.js"></script>
     <script src="/static/css/vendor/highlight.min.js"></script>
     <link rel="stylesheet" href="/static/css/vendor/highlight-github-dark.min.css">
     <link rel="stylesheet" href="/static/css/style.css">
 </head>
-<body class="h-screen flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}" data-auth-enabled="{{ 'true' if is_auth_enabled else 'false' }}">
+<body class="h-screen flex flex-col" data-currency="{{ currency_symbol }}" data-hide-thinking="{{ 'true' if hide_thinking else 'false' }}">
     <div id="usage-bar"></div>
     <header class="flex items-center justify-between px-5 py-2 border-b border-slate-800/50">
         <div class="flex items-center gap-2 flex-1 min-w-0">
             <h1 class="text-lg font-bold tracking-tight shrink-0">🎼</h1>
             <div id="orch-tabs" class="flex items-center gap-1.5 overflow-x-auto no-scrollbar"></div>
### a755646c6 #91: client info page + proxy-only models + connection indicator

diff --git a/app/static/js/app.js b/app/static/js/app.js
index dce523d62..a4595330c 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -245,19 +245,23 @@ async function loadMoreLogs() {
 
 
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
@@ -1128,15 +1132,27 @@ let agentColors = {};
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
@@ -4155,19 +4171,59 @@ function switchLeftTab(tab) {
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
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index c7dc8b35c..5d30665d3 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -22,10 +22,11 @@
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
@@ -155,15 +156,17 @@
         <div id="file-panel" class="w-[250px] border-r border-slate-800/50 flex flex-col overflow-hidden">
             <div class="flex border-b border-slate-800/50">
                 <button data-left-tab="files" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-white border-b-2 border-indigo-500 transition-colors" onclick="switchLeftTab('files')">FILES</button>
                 <button data-left-tab="tasks" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('tasks')">TASKS</button>
                 <button data-left-tab="jobs" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('jobs')">JOBS</button>
+                {% if is_auth_enabled %}<button data-left-tab="client" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('client')">CLIENT</button>{% endif %}
                 <button id="open-folder-btn" title="Open in file manager" style="background:none;border:none;cursor:pointer;font-size:14px;opacity:0.5;padding:2px;transition:opacity 0.15s" onmouseenter="this.style.opacity='0.9'" onmouseleave="this.style.opacity='0.5'">📂</button>
### cbe4f00b0 Revert "#91: client info page + proxy-only models + connection indicator"

diff --git a/app/static/js/app.js b/app/static/js/app.js
index a4595330c..dce523d62 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -245,23 +245,19 @@ async function loadMoreLogs() {
 
 
 // === Models ===
 async function loadModels() {
     try {
-        const data = await api('/api/models');
-        const models = data.models || [];
+        const models = await api('/api/models');
         const select = $('#orch-model');
-        if (select) {
-            select.innerHTML = '';
-            for (const m of models) {
-                const opt = document.createElement('option');
-                opt.value = m.id;
-                opt.textContent = `${m.name} (${m.id})`;
-                select.appendChild(opt);
-            }
+        select.innerHTML = '';
+        for (const m of models) {
+            const opt = document.createElement('option');
+            opt.value = m.id;
+            opt.textContent = `${m.name} (${m.id})`;
+            select.appendChild(opt);
         }
-        _updateProxyStatus(data.proxy_connected);
     } catch {}
 }
 
 // === Profile / Pipeline / Role dropdowns (модалка создания корня) ===
 let _pipelineRoles = {};  // карта pipeline-name → [roles]
@@ -1132,27 +1128,15 @@ let agentColors = {};
 let _MODELS = [];
 let _modelsLoaded = false;
 async function _ensureModels() {
     if (_modelsLoaded) return;
     try {
-        const data = await api('/api/models');
-        const models = data.models || [];
+        const models = await api('/api/models');
         _MODELS = models.map(m => ({ id: m.id, label: m.name }));
         _modelsLoaded = true;
     } catch {}
 }
-function _updateProxyStatus(connected) {
-    const el = document.getElementById('proxy-status');
-    if (!el) return;
-    if (connected) {
-        el.textContent = '🟢';
-        el.title = 'Proxy connected';
-    } else {
-        el.textContent = '🔴';
-        el.title = 'Proxy offline — no models available';
-    }
-}
 async function _showModelPicker(agentName, currentModel, anchor) {
     const existing = document.getElementById('model-picker-dd');
     if (existing) { existing.remove(); return; }
     await _ensureModels();
     const dd = document.createElement('div');
@@ -4171,59 +4155,19 @@ function switchLeftTab(tab) {
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
-}
-
-async function loadClientInfo() {
-    const panel = document.getElementById('client-panel');
-    if (!panel) return;
-    panel.innerHTML = '<span class="text-slate-500">Loading...</span>';
-    try {
-        const data = await api('/api/models');
-        const models = data.models || [];
-        const connected = data.proxy_connected;
-        const currency = document.body.dataset.currency || '$';
-        let html = `<div class="space-y-3">`;
-        html += `<div class="flex items-center gap-2 mb-2">
-            <span class="text-sm font-bold text-white">Client Info</span>
-            <span class="text-xs ${connected ? 'text-emerald-400' : 'text-red-400'}">${connected ? '🟢 Proxy connected' : '🔴 Proxy offline'}</span>
-        </div>`;
-        if (!models.length) {
-            html += `<div class="text-slate-500 italic">No models available</div>`;
-        } else {
-            html += `<div class="text-xs text-slate-500 mb-1">${models.length} models available</div>`;
-            for (const m of models) {
-                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k ctx` : '';
-                const price = (m.price_input != null && m.price_output != null)
-                    ? `${currency}${m.price_input}/M in · ${currency}${m.price_output}/M out`
-                    : '';
-                html += `<div class="p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
-                    <div class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</div>
-                    <div class="text-[10px] text-slate-500 font-mono">${escHtml(m.id)}</div>
-                    <div class="text-[10px] text-slate-400 mt-0.5">${[ctx, price].filter(Boolean).join(' · ')}</div>
-                </div>`;
-            }
-        }
-        html += `</div>`;
-        panel.innerHTML = html;
-    } catch (e) {
-        panel.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
-    }
 }
 
 const STATUS_ORDER = ['in_progress', 'done', 'new', 'backlog', 'paid', 'cancelled'];
 const STATUS_COLORS = {
     in_progress: 'bg-blue-400', done: 'bg-amber-400', new: 'bg-white',
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index 5d30665d3..c7dc8b35c 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -22,11 +22,10 @@
             <button id="new-orch-btn" class="px-2.5 py-1.5 bg-slate-800/50 hover:bg-slate-700 border border-dashed border-slate-700 rounded-full text-xs transition-colors shrink-0" title="New orchestrator">+</button>
             <button id="hidden-tabs-btn" class="px-2 py-1.5 hover:bg-slate-700 rounded-full text-xs transition-colors text-slate-500 hover:text-slate-300 shrink-0 hidden" title="Show hidden tabs">👁</button>
         </div>
         <div class="flex items-center gap-3 text-xs text-slate-600 shrink-0">
             <span id="stats-line"></span>
-            {% if is_auth_enabled %}<span id="proxy-status" class="text-xs cursor-default" title="Proxy status">⏳</span>{% endif %}
             <div class="relative">
                 <button id="proxy-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400 flex items-center gap-1" title="Proxy settings">
                     <span id="proxy-flag">🌐</span>
                     <span id="proxy-ip" class="text-[10px] text-slate-500"></span>
                 </button>
@@ -156,17 +155,15 @@
         <div id="file-panel" class="w-[250px] border-r border-slate-800/50 flex flex-col overflow-hidden">
             <div class="flex border-b border-slate-800/50">
                 <button data-left-tab="files" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-white border-b-2 border-indigo-500 transition-colors" onclick="switchLeftTab('files')">FILES</button>
                 <button data-left-tab="tasks" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('tasks')">TASKS</button>
                 <button data-left-tab="jobs" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('jobs')">JOBS</button>
-                {% if is_auth_enabled %}<button data-left-tab="client" class="left-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors" onclick="switchLeftTab('client')">CLIENT</button>{% endif %}
                 <button id="open-folder-btn" title="Open in file manager" style="background:none;border:none;cursor:pointer;font-size:14px;opacity:0.5;padding:2px;transition:opacity 0.15s" onmouseenter="this.style.opacity='0.9'" onmouseleave="this.style.opacity='0.5'">📂</button>
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