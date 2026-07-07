// Cap DOM nodes to avoid memory growth during long agent sessions
const MAX_CHAT_NODES = 500;
function fmtCost(v) { v = Number(v) || 0; if (v === 0) return '$0.00'; if (v < 0.01) return '$' + v.toFixed(4); return '$' + v.toFixed(2); }
let currentScope = null;
let selectedAgent = null;
let chatLogs = {};
// localMessages tracks messages sent from this tab so SSE echo doesn't create duplicates
let localMessages = new Set();
let pendingUserMsgs = [];
let pendingBubble = null;
let uiDebounceTimer = null;
let refreshController = null;
// UI debounce: rapid-fire messages from the user are batched into one send before the timer fires
const UI_DEBOUNCE_MS = 2500;
let scrollAfterLoad = true;
let drafts = {};

window.compactMode = localStorage.getItem('compactToolMode') === 'true';

function saveDraft() {
    if (selectedAgent) drafts[selectedAgent] = { text: $('#chat-input').value, images: [...pastedImages] };
}
function restoreDraft() {
    const d = drafts[selectedAgent] || {};
    $('#chat-input').value = d.text || '';
    clearPastePreview();
    if (d.images && d.images.length) {
        pastedImages = [...d.images];
        d.images.forEach(url => showImagePreview(url));
    }
}

document.addEventListener('DOMContentLoaded', () => {
    $('#send-btn').addEventListener('click', sendChat);
    $('#stop-btn').addEventListener('click', stopAgent);
    $('#chat-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $('#chat-input').addEventListener('paste', handlePaste);
    $('#chat-input').addEventListener('input', () => {
        const text = $('#chat-input').value;
        const container = $('#paste-preview');
        if (!container) return;
        for (const w of [...container.querySelectorAll('[data-url]')]) {
            const fp = w.dataset.filePath || w.dataset.url;
            if (!text.includes(fp)) {
                w.remove();
                pastedImages = pastedImages.filter(u => u !== w.dataset.url);
            }
        }
        if (!container.children.length) container.remove();
    });
    const _rh = $('#input-resize-handle');
    if (_rh) {
        const _ta = $('#chat-input');
        let _ry, _rh0;
        _rh.addEventListener('mousedown', (e) => {
            _ry = e.clientY;
            _rh0 = _ta.offsetHeight;
            const onMove = (e) => { _ta.style.height = Math.max(40, Math.min(300, _rh0 + (_ry - e.clientY))) + 'px'; };
            const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            e.preventDefault();
        });
    }
    $('#orch-picker').addEventListener('change', onOrchestratorChange);
    $('#new-orch-btn').addEventListener('click', () => {
        $('#new-orch-modal').classList.remove('hidden');
        $('#new-orch-modal').classList.add('flex');
        $('#project-picker').classList.add('hidden');
        loadProfilesDropdown();
        loadPipelinesDropdown();
        $('#orch-cwd').focus();
    });
    $('#orch-pipeline').addEventListener('change', populateRoleDropdown);
    $('#modal-close').addEventListener('click', closeModal);
    $('#new-orch-modal').addEventListener('click', (e) => {
        if (e.target === $('#new-orch-modal')) closeModal();
    });
    $('#create-orch-btn').addEventListener('click', createOrchestrator);
    $('#orch-cwd').addEventListener('input', () => {
        const path = $('#orch-cwd').value.trim();
        if (path && !$('#orch-name').value.trim()) {
            $('#orch-name').value = autoNameFromPath(path);
        }
    });
    $('#orch-cwd').addEventListener('change', () => {
        const path = $('#orch-cwd').value.trim();
        if (path) $('#orch-name').value = autoNameFromPath(path);
    });
    $('#browse-btn')?.addEventListener('click', showProjectPicker);
    initTabContextMenu();
    initHiddenTabsBtn();
    initDropHint();
    $('#restart-btn').addEventListener('click', restartServer);
    // Enterprise: remove dev-only UI before init binds event listeners
    if (document.body.dataset.authEnabled === 'true') {
        document.querySelector('#proxy-btn')?.parentElement?.remove();
        document.getElementById('profiles-btn')?.parentElement?.remove();
        const clientBtn = document.getElementById('client-btn');
        if (clientBtn) clientBtn.addEventListener('click', openClientModal);
        const clientClose = document.getElementById('client-modal-close');
        if (clientClose) clientClose.addEventListener('click', closeClientModal);
        const clientModal = document.getElementById('client-modal');
        if (clientModal) clientModal.addEventListener('click', (e) => { if (e.target === clientModal) closeClientModal(); });
    }
    initProxy();
    initProfilesManager();
    $('#orch-name')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
    $('#orch-cwd')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
    $('#view-prompt-btn').addEventListener('click', openPromptModal);
    $('#compact-btn').addEventListener('click', compactAgent);
    $('#restart-cli-btn').addEventListener('click', restartCli);
    $('#prompt-modal-close').addEventListener('click', closePromptModal);
    $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); closeClientModal(); } });
    const compactBtn = $('#compact-toggle-btn');
    if (compactBtn) {
        compactBtn.textContent = window.compactMode ? '📄' : '📋';
        compactBtn.title = window.compactMode ? 'Switch to normal view' : 'Switch to compact view';
        compactBtn.addEventListener('click', () => {
            window.compactMode = !window.compactMode;
            localStorage.setItem('compactToolMode', window.compactMode);
            compactBtn.textContent = window.compactMode ? '📄' : '📋';
            compactBtn.title = window.compactMode ? 'Switch to normal view' : 'Switch to compact view';
            $('#chat').innerHTML = '';
            if (chatLogs[selectedAgent]) { chatLogs[selectedAgent].lastId = 0; chatLogs[selectedAgent].firstId = null; chatLogs[selectedAgent].initialCount = 0; }
            scrollAfterLoad = true;
            connectSSE();
        });
    }
    const openFolderBtn = $('#open-folder-btn');
    if (openFolderBtn) {
        openFolderBtn.addEventListener('click', () => {
            if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
        });
    }
    loadModels();
    loadOrchestrators();
    scheduleRefresh();
    initFilePreviewModal();
    initUsageBar();
    initHeartbeat();
});

let eventSource = null;

function scheduleRefresh() {
    setTimeout(async () => {
        await refreshSessions();
        scheduleRefresh();
    }, 3000);
}

// SSE reconnects on error — server may restart mid-session, don't lose the log stream
function connectSSE() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (!selectedAgent || !currentScope) return;
    const targetAgent = selectedAgent;
    const lastId = chatLogs[selectedAgent]?.lastId || 0;
    const limitParam = lastId === 0 ? '&limit=100' : '';
    const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
    eventSource = new EventSource(url);
    eventSource.onmessage = (event) => {
        if (selectedAgent !== targetAgent) return;
        try {
            const l = JSON.parse(event.data);
            if (l.type === 'user_message' && localMessages.size > 0) {
                const isLocal = localMessages.has(l.content) ||
                    [...localMessages].some(m => l.content.endsWith(m)) ||
                    [...localMessages].some(m => l.content.includes(m));
                if (isLocal) {
                    for (const m of localMessages) {
                        if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                            localMessages.delete(m);
                            break;
                        }
                    }
                } else {
                    addChatEntry(l.type, l.content, l.ts, null, l);
                }
            } else {
                addChatEntry(l.type, l.content, l.ts, null, l);
            }
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null, initialCount: 0 };
            // Live stream partials carry no id — skip id bookkeeping for them
            if (Number.isFinite(l.id)) {
                if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                    chatLogs[selectedAgent].firstId = l.id;
                }
                // Count only the initial history burst (scrollAfterLoad is true during it).
                // Load-more shows only if that burst hit the page-size cap (100) → more may exist.
                // Log IDs are global (shared across sessions), so firstId can't tell "start of history".
                if (scrollAfterLoad) {
                    chatLogs[selectedAgent].initialCount++;
                    updateLoadMoreBtn();
                }
            }
            if (scrollAfterLoad) {
                $('#chat').scrollTop = $('#chat').scrollHeight;
                clearTimeout(window._scrollResetTimer);
                window._scrollResetTimer = setTimeout(() => { scrollAfterLoad = false; }, 500);
            }
        } catch (e) { console.warn('SSE parse:', e); }
    };
    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        _onServerError();
        setTimeout(() => { if (selectedAgent === targetAgent) connectSSE(); }, 2000);
    };
}

const _LOAD_MORE_THRESHOLD = 100;  // matches initial history page size (connectSSE limit=100)
function _addLoadMoreBtn() {
    if ($('#load-more-btn')) return;
    const btn = document.createElement('div');
    btn.id = 'load-more-btn';
    btn.className = 'text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
    btn.textContent = '▲ Load 500 more';
    btn.addEventListener('click', loadMoreLogs);
    $('#chat').prepend(btn);
}
function updateLoadMoreBtn() {
    // Show only if the initial burst filled the page — otherwise all history is loaded.
    // Can't use firstId: log IDs are global, a fresh session's first id is far above 1.
    const initialCount = chatLogs[selectedAgent]?.initialCount || 0;
    if (initialCount < _LOAD_MORE_THRESHOLD) {
        const existing = $('#load-more-btn');
        if (existing) existing.remove();
        return;
    }
    _addLoadMoreBtn();
}

async function loadMoreLogs() {
    if (!selectedAgent || !currentScope) return;
    const firstId = chatLogs[selectedAgent]?.firstId;
    if (!firstId) return;
    const btn = $('#load-more-btn');
    if (btn) { btn.textContent = '⏳ Loading…'; btn.style.pointerEvents = 'none'; }
    try {
        const res = await fetch(`/api/sessions/${selectedAgent}/logs?scope=${encodeURIComponent(currentScope)}&before_id=${firstId}&limit=500`);
        const logs = await res.json();
        if (!Array.isArray(logs) || logs.length === 0) {
            if (btn) btn.remove();
            return;
        }
        const chat = $('#chat');
        const oldHeight = chat.scrollHeight;
        if (btn) btn.remove();
        // prepend в правильном порядке (logs уже ASC из db)
        // фиксируем anchor = текущий firstChild, вставляем все перед ним по порядку
        const anchor = chat.firstChild;
        for (const l of logs) {
            addChatEntry(l.type, l.content, l.ts, anchor);
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null, initialCount: 0 };
            if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                chatLogs[selectedAgent].firstId = l.id;
            }
        }
        chat.scrollTop = chat.scrollHeight - oldHeight;
        // Full page (500) returned → more may exist, re-add button. Fewer → reached the start.
        if (logs.length >= 500) _addLoadMoreBtn();
    } catch (e) {
        if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
        console.warn('loadMoreLogs error:', e);
    }
}


// === Models ===
async function loadModels() {
    try {
        const data = await api('/api/models');
        const models = data.models || [];
        _MODELS = models.map(m => ({ id: m.id, label: m.name }));
        _modelsLoaded = true;
        const select = $('#orch-model');
        if (select) {
            select.innerHTML = '';
            for (const m of models) {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = `${m.name} (${m.id})`;
                select.appendChild(opt);
            }
        }
        _updateProxyStatus(data.proxy_connected);
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
        if (def) select.value = def.name;
    } catch {}
}

async function loadPipelinesDropdown() {
    try {
        const pipelines = await api('/api/pipelines');
        const select = $('#orch-pipeline');
        select.innerHTML = '';
        _pipelineRoles = {};
        for (const p of pipelines) {
            _pipelineRoles[p.name] = p.roles || [];
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.name;
            select.appendChild(opt);
        }
        populateRoleDropdown();
    } catch {}
}

function populateRoleDropdown() {
    const select = $('#orch-role');
    select.innerHTML = '';
    const roles = _pipelineRoles[$('#orch-pipeline').value] || [];
    for (const r of roles) {
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = r;
        select.appendChild(opt);
    }
}

// === Modal ===
function closeModal() {
    $('#new-orch-modal').classList.add('hidden');
    $('#new-orch-modal').classList.remove('flex');
    $('#orch-error').classList.add('hidden');
}

function closePromptModal() {
    $('#prompt-modal').classList.add('hidden');
    $('#prompt-modal').classList.remove('flex');
}

async function compactAgent() {
    if (!selectedAgent || !currentScope) return;
    const btn = $('#compact-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        const res = await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/compact`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: currentScope}),
        });
        if (res.error) throw new Error(res.error);
        delete contextCache[`${currentScope}:${selectedAgent}`];
        await fetchAgentContext(selectedAgent);
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
        setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 2000);
    }
}

async function restartCli() {
    if (!selectedAgent || !currentScope) return;
    const btn = $('#restart-cli-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/restart-cli`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: currentScope}),
        });
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
        setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 2000);
    }
}

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
        _renderPromptBlocks(body, blocks, true);
    } catch (e) {
        body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
    }
}

function _renderPromptBlocks(container, blocks) {
    const TYPE_COLORS = { file: '#3b82f6', module: '#a78bfa', dynamic: '#f59e0b', skill: '#22c55e' };
    const counts = {};
    for (const b of blocks) counts[b.type] = (counts[b.type] || 0) + 1;
    const totalChars = blocks.reduce((s, b) => s + (b.size || 0), 0);
    const totalTokens = Math.round(totalChars / 4);

    let html = `<div class="pb-summary">
        <span class="pb-stat"><b>${blocks.length}</b> blocks</span>
        ${counts.file ? `<span class="pb-stat" style="color:#3b82f6"><b>${counts.file}</b> files</span>` : ''}
        ${counts.module ? `<span class="pb-stat" style="color:#a78bfa"><b>${counts.module}</b> modules</span>` : ''}
        ${counts.dynamic ? `<span class="pb-stat" style="color:#f59e0b"><b>${counts.dynamic}</b> dynamic</span>` : ''}
        ${counts.skill ? `<span class="pb-stat" style="color:#22c55e"><b>${counts.skill}</b> skills</span>` : ''}
        <span class="pb-stat"><b>~${totalTokens >= 1000 ? (totalTokens/1000).toFixed(1)+'k' : totalTokens}</b> tokens</span>
    </div>`;

    blocks.forEach((b, i) => {
        const color = TYPE_COLORS[b.type] || '#64748b';
        const tokens = Math.round((b.size || 0) / 4);
        const tokStr = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
        html += `<div class="pb-block pb-open" style="border-left-color:${color}" data-pb-idx="${i}">
            <div class="pb-header" onclick="this.parentElement.classList.toggle('pb-open')">
                <span class="pb-chevron">▸</span>
                <span class="pb-tag" style="background:${color}22;color:${color}">${b.type}</span>
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
        const bodyEl = el.querySelector('.pb-body');
        if (b.content) {
            bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
            bodyEl.dataset.loaded = '1';
        }
        el.querySelector('.pb-header').addEventListener('click', () => {
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
}

async function openFilePreview(path) {
    const modal = $('#file-preview-modal');
    const pathEl = $('#file-preview-path');
    const contentEl = $('#file-preview-content');
    const openBtn = $('#file-preview-open');
    const dlBtn = $('#file-preview-download');
    pathEl.textContent = path;
    contentEl.textContent = 'Loading…';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const rawUrl = `/api/files/raw?path=${encodeURIComponent(path)}`;
    const fileName = path.split('/').pop() || 'file';
    dlBtn.href = rawUrl;
    dlBtn.download = fileName;
    dlBtn.classList.remove('hidden');
    if (/\.html?$/i.test(path)) {
        openBtn.href = rawUrl;
        openBtn.classList.remove('hidden');
        contentEl.className = 'flex-1 p-0';
        contentEl.style.cssText = 'overflow:hidden;max-height:calc(80vh - 48px)';
        contentEl.innerHTML = `<iframe src="${rawUrl}" style="width:100%;height:100%;border:none;border-radius:0 0 12px 12px;min-height:60vh" sandbox="allow-scripts allow-same-origin"></iframe>`;
        return;
    }
    openBtn.classList.add('hidden');
    try {
        const res = await fetch(`/api/files/content?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (data.error) {
            const sizeStr = data.size ? ` (${(data.size / 1024).toFixed(1)} KB)` : '';
            if (data.error === 'binary file' && /\.(png|jpg|jpeg|gif|webp|bmp|ico|svg)$/i.test(path)) {
                contentEl.innerHTML = `<img src="/api/files/raw?path=${encodeURIComponent(path)}" style="max-width:100%;max-height:70vh;border-radius:8px">`;
            } else {
                contentEl.textContent = `⚠ ${data.error}${sizeStr}`;
            }
        } else if (/\.md$/i.test(path)) {
            contentEl.className = 'flex-1 text-xs text-slate-300 markdown-body p-4';
            contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;white-space:normal;max-height:calc(80vh - 48px)';
            const dir = path.substring(0, path.lastIndexOf('/'));
            const renderer = new marked.Renderer();
            renderer.image = (token) => {
                const h = typeof token === 'object' ? (token.href || '') : (token || '');
                const t = typeof token === 'object' ? (token.title || '') : '';
                const a = typeof token === 'object' ? (token.text || '') : '';
                const src = (h && !h.startsWith('http') && !h.startsWith('/api/'))
                    ? `/api/files/raw?path=${encodeURIComponent(dir + '/' + h)}`
                    : h;
                return `<img src="${src}"${a ? ` alt="${a}"` : ''}${t ? ` title="${t}"` : ''} loading="lazy" style="max-width:100%;border-radius:6px;margin:4px 0;cursor:pointer" onclick="openFilePreview('${h}')">`;
            };
            // Strip prompt-style XML tags (<platform>, <rules>) — they make marked treat
            // wrapped markdown as raw HTML, so ## headings / - lists never render.
            contentEl.innerHTML = DOMPurify.sanitize(marked.parse(_stripXmlTags(data.content), { renderer }), { ADD_ATTR: ['loading'] });
        } else if (/\.svg$/i.test(path)) {
            contentEl.innerHTML = `<img src="/api/files/raw?path=${encodeURIComponent(path)}" style="max-width:100%;max-height:70vh;border-radius:8px">`;
        } else {
            const ext = (path.match(/\.(\w+)$/)?.[1] || '').toLowerCase();
            const LANG_MAP = {
                py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',
                html:'xml',css:'css',json:'json',xml:'xml',yaml:'yaml',yml:'yaml',
                sh:'bash',bash:'bash',sql:'sql',go:'go',rs:'rust',php:'php',
                rb:'ruby',java:'java',kt:'kotlin',swift:'swift',c:'c',cpp:'cpp',
                toml:'ini',ini:'ini',dockerfile:'dockerfile',
            };
            const raw = data.content.replace(/^\s*\d+\t/gm, '');

            if ((ext === 'csv' || ext === 'tsv') && raw.trim()) {
                const sep = ext === 'tsv' ? '\t' : ',';
                const rows = raw.trim().split('\n').map(r => r.split(sep));
                contentEl.className = 'flex-1 text-xs p-4 markdown-body';
                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';
                let html = '<table><thead><tr>';
                for (const h of (rows[0] || [])) html += `<th>${DOMPurify.sanitize(h.trim())}</th>`;
                html += '</tr></thead><tbody>';
                for (const row of rows.slice(1)) {
                    html += '<tr>';
                    for (const cell of row) html += `<td>${DOMPurify.sanitize(cell.trim())}</td>`;
                    html += '</tr>';
                }
                html += '</tbody></table>';
                contentEl.innerHTML = html;
            } else if (ext === 'json') {
                let pretty = raw;
                try { pretty = JSON.stringify(JSON.parse(raw), null, 2); } catch {}
                contentEl.className = 'flex-1 text-xs p-4';
                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';
                const pre = document.createElement('pre');
                pre.style.cssText = 'margin:0;background:transparent';
                const code = document.createElement('code');
                code.className = 'language-json';
                code.textContent = pretty;
                pre.appendChild(code);
                contentEl.innerHTML = '';
                contentEl.appendChild(pre);
                if (window.hljs) hljs.highlightElement(code);
            } else if (LANG_MAP[ext] && window.hljs) {
                contentEl.className = 'flex-1 text-xs p-4';
                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';
                const pre = document.createElement('pre');
                pre.style.cssText = 'margin:0;background:transparent';
                const code = document.createElement('code');
                code.className = `language-${LANG_MAP[ext]}`;
                code.textContent = raw;
                pre.appendChild(code);
                contentEl.innerHTML = '';
                contentEl.appendChild(pre);
                hljs.highlightElement(code);
            } else {
                contentEl.className = 'flex-1 text-xs p-4 text-slate-300';
                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px);white-space:pre;word-wrap:normal';
                contentEl.textContent = raw;
            }
        }
    } catch (e) {
        contentEl.textContent = `Error: ${e.message}`;
    }
}

function closeFilePreview() {
    const modal = $('#file-preview-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    const openBtn = $('#file-preview-open');
    if (openBtn) openBtn.classList.add('hidden');
    const dlBtn = $('#file-preview-download');
    if (dlBtn) dlBtn.classList.add('hidden');
    const contentEl = $('#file-preview-content');
    if (contentEl) contentEl.innerHTML = '';
}

function initFilePreviewModal() {
    const modal = $('#file-preview-modal');
    if (!modal) return;
    $('#file-preview-close').addEventListener('click', closeFilePreview);
}

async function showProjectPicker() {
    const picker = $('#project-picker');
    picker.innerHTML = '<div class="p-2 text-xs text-slate-500">Loading...</div>';
    picker.classList.remove('hidden');
    try {
        const projects = await api('/api/projects');
        picker.innerHTML = '';
        for (const p of projects) {
            const item = document.createElement('div');
            item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-slate-800 border-b border-slate-800/50';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'text-white font-medium';
            nameSpan.textContent = p.name;
            const pathSpan = document.createElement('span');
            pathSpan.className = 'text-slate-500 text-xs';
            pathSpan.textContent = ' ' + p.path;
            item.append(nameSpan, pathSpan);
            item.addEventListener('click', () => {
                $('#orch-cwd').value = p.path;
                $('#orch-name').value = p.name + '-orchestrator';
                picker.classList.add('hidden');
            });
            picker.appendChild(item);
        }
    } catch { picker.innerHTML = '<div class="p-2 text-xs text-red-400">Failed to load</div>'; }
}

function autoNameFromPath(path) {
    const parts = path.replace(/\/+$/, '').split('/');
    const folder = parts[parts.length - 1] || '';
    return folder + '-orchestrator';
}

async function createOrchestrator() {
    const name = $('#orch-name').value.trim();
    const cwd = $('#orch-cwd').value.trim();
    const model = $('#orch-model').value;
    const profile = 'personal';
    const pipeline = 'default';
    const role = 'orchestrator';
    const errEl = $('#orch-error');
    if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
    const btn = $('#create-orch-btn');
    btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
    try {
        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
        closeModal(); $('#orch-name').value = ''; $('#orch-cwd').value = '';
        currentScope = null;
        await loadOrchestrators();
        selectOrchestrator(name, cwd.replace(/\/+$/, ''));
    } catch (e) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    finally { btn.disabled = false; btn.textContent = 'Create Orchestrator'; }
}

async function restartServer() {
    const btn = $('#restart-btn');
    btn.disabled = true; btn.textContent = '⏳';
    try {
        await api('/api/restart', { method: 'POST' });
    } catch {}
    setTimeout(() => location.reload(), 3000);
}

async function deleteOrchestrator() {
    if (!currentScope || !selectedAgent) return;
    if (!confirm(`Delete "${selectedAgent}" and all its workers?`)) return;
    try {
        await api(`/api/orchestrators/${selectedAgent}?scope=${encodeURIComponent(currentScope)}`, { method: 'DELETE' });
        localStorage.removeItem('lastOrchScope');
        localStorage.removeItem('lastOrchName');
        currentScope = null;
        selectedAgent = null;
        await loadOrchestrators();
    } catch (e) { alert(`Delete failed: ${e.message}`); }
}

// === Orchestrator Picker ===
let orchData = [];
const _unreadTabs = new Set();

async function loadOrchestrators() {
    try {
        const allOrchs = await api('/api/orchestrators');
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

        const sorted = [...orchData].sort((a, b) => {
            const ai = recent.indexOf(a.name);
            const bi = recent.indexOf(b.name);
            if (ai >= 0 && bi >= 0) return ai - bi;
            if (ai >= 0) return -1;
            if (bi >= 0) return 1;
            return 0;
        });

        renderOrchTabs(sorted);

        if (orchData.length > 0 && !currentScope) {
            const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
            if (match) {
                selectOrchestrator(match.name, match.scope);
            } else {
                selectOrchestrator(sorted[0].name, sorted[0].scope);
            }
        }
    } catch {}
}

function _applyTabOrder(list) {
    const saved = JSON.parse(localStorage.getItem('tabOrder') || '[]');
    if (!saved.length) return list;
    return [...list].sort((a, b) => {
        const ai = saved.indexOf(a.name);
        const bi = saved.indexOf(b.name);
        if (ai >= 0 && bi >= 0) return ai - bi;
        if (ai >= 0) return -1;
        if (bi >= 0) return 1;
        return 0;
    });
}

function _saveTabOrder() {
    const tabs = $('#orch-tabs');
    const order = [...tabs.querySelectorAll('.orch-tab')].map(t => t.dataset.orchName);
    localStorage.setItem('tabOrder', JSON.stringify(order));
}

function _getHiddenTabs() {
    try { return new Set(JSON.parse(localStorage.getItem('orchestra_hidden_tabs') || '[]')); } catch { return new Set(); }
}
function _setHiddenTabs(set) {
    localStorage.setItem('orchestra_hidden_tabs', JSON.stringify([...set]));
}

function renderOrchTabs(sorted) {
    const tabs = $('#orch-tabs');
    tabs.innerHTML = '';
    const ordered = _applyTabOrder(sorted);
    const hidden = _getHiddenTabs();
    let dragTab = null;
    _updateHiddenBtn();
    for (const o of ordered) {
        if (hidden.has(o.name)) continue;
        const tab = document.createElement('button');
        tab.className = `orch-tab ${o.name === selectedAgent && o.scope === currentScope ? 'active' : ''}`;
        tab.dataset.orchName = o.name;
        tab.draggable = true;
        const dot = document.createElement('span');
        dot.className = 'tab-dot';
        dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : o.any_waiting ? '#f59e0b' : '#eab308';
        const label = document.createElement('span');
        const shortName = o.name.replace(/-orchestrator$/, '');
        label.textContent = shortName;
        tab.append(dot, label);
        tab.title = o.scope;
        tab.style.position = 'relative';
        if (_unreadTabs.has(o.scope)) {
            const unread = document.createElement('span');
            unread.className = 'tab-unread';
            unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
            tab.appendChild(unread);
        }
        tab.addEventListener('click', () => selectOrchestrator(o.name, o.scope));
        tab.addEventListener('dragstart', (e) => {
            dragTab = tab;
            tab.style.opacity = '0.4';
            e.dataTransfer.effectAllowed = 'move';
        });
        tab.addEventListener('dragend', () => {
            tab.style.opacity = '';
            dragTab = null;
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
        });
        tab.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (!dragTab || dragTab === tab) return;
            const rect = tab.getBoundingClientRect();
            const mid = rect.left + rect.width / 2;
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
            if (e.clientX < mid) {
                tab.style.borderLeft = '2px solid #6366f1';
            } else {
                const next = tab.nextElementSibling;
                if (next) next.style.borderLeft = '2px solid #6366f1';
            }
        });
        tab.addEventListener('drop', (e) => {
            e.preventDefault();
            if (!dragTab || dragTab === tab) return;
            const rect = tab.getBoundingClientRect();
            const mid = rect.left + rect.width / 2;
            if (e.clientX < mid) {
                tabs.insertBefore(dragTab, tab);
            } else {
                tabs.insertBefore(dragTab, tab.nextSibling);
            }
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
            _saveTabOrder();
        });
        tabs.appendChild(tab);
    }
}

let _dropDragCounter = 0;
function _hideDropHint() {
    _dropDragCounter = 0;
    const input = $('#chat-input');
    if (!input) return;
    if (input.dataset.origPlaceholder) {
        input.placeholder = input.dataset.origPlaceholder;
        delete input.dataset.origPlaceholder;
    }
    input.classList.remove('border-indigo-400');
}
function initDropHint() {
    document.addEventListener('dragenter', (e) => {
        if (!e.dataTransfer?.types?.includes('Files')) return;
        _dropDragCounter++;
        const input = $('#chat-input');
        if (input) {
            if (!input.dataset.origPlaceholder) input.dataset.origPlaceholder = input.placeholder;
            input.placeholder = '📎 Drop files here';
            input.classList.add('border-indigo-400');
        }
    });
    document.addEventListener('dragleave', (e) => {
        if (!e.dataTransfer?.types?.includes('Files')) return;
        _dropDragCounter--;
        if (_dropDragCounter <= 0) _hideDropHint();
    });
    document.addEventListener('drop', () => _hideDropHint());
}

function initTabContextMenu() {
    let menu = null;
    const close = () => { if (menu) { menu.remove(); menu = null; } };
    document.addEventListener('click', close);
    document.addEventListener('contextmenu', (e) => {
        const tab = e.target.closest('.orch-tab');
        if (!tab) { close(); return; }
        e.preventDefault();
        close();
        const name = tab.dataset.orchName;
        const scope = tab.title;
        menu = document.createElement('div');
        menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:120px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
        const mkItem = (label, color, fn) => {
            const item = document.createElement('div');
            item.style.cssText = `padding:6px 14px;font-size:12px;color:${color};cursor:pointer;white-space:nowrap`;
            item.textContent = label;
            item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
            item.addEventListener('mouseleave', () => item.style.background = '');
            item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
            return item;
        };
        menu.appendChild(mkItem('👁 Скрыть', '#94a3b8', () => {
            const h = _getHiddenTabs(); h.add(name); _setHiddenTabs(h);
            renderOrchTabs(orchData);
        }));
        menu.appendChild(mkItem('📁 Сменить папку', '#60a5fa', () => {
            changeOrchScope(name, scope);
        }));
        menu.appendChild(mkItem('🗑 Удалить', '#ef4444', () => {
            openDeleteOrchModal(name, scope);
        }));
        document.body.appendChild(menu);
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
    });
}

function openDeleteOrchModal(name, scope) {
    const modal = $('#delete-orch-modal');
    if (!modal) {
        if (!confirm(`Delete "${name}" and all its workers?`)) return;
        api(`/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' })
            .then(() => loadOrchestrators())
            .catch(e => alert(`Delete failed: ${e.message}`));
        return;
    }
    $('#delete-orch-name').textContent = `"${name}"`;
    $('#delete-tg-topics').checked = false;
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    const close = () => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    };

    $('#delete-orch-confirm').onclick = async () => {
        const deleteTopics = $('#delete-tg-topics').checked;
        close();
        try {
            const url = `/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}&delete_tg_topics=${deleteTopics}`;
            await api(url, { method: 'DELETE' });
            loadOrchestrators();
        } catch (e) {
            alert(`Delete failed: ${e.message}`);
        }
    };
    $('#delete-orch-cancel').onclick = close;
    $('#delete-orch-modal-close').onclick = close;
    modal.onclick = (e) => { if (e.target === modal) close(); };
}

function changeOrchScope(name, oldScope) {
    const modal = $('#change-scope-modal');
    if (!modal) return;
    const pathInput = $('#change-scope-path');
    const errorEl = $('#change-scope-error');
    const picker = $('#change-scope-picker');
    $('#change-scope-name').textContent = name;
    pathInput.value = oldScope;
    errorEl.classList.add('hidden');
    picker.classList.add('hidden');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    pathInput.focus();
    pathInput.select();

    const close = () => { modal.classList.remove('flex'); modal.classList.add('hidden'); };

    const doMove = async () => {
        const ns = pathInput.value.trim().replace(/\/+$/, '');
        if (!ns || ns === oldScope) { close(); return; }
        errorEl.classList.add('hidden');
        try {
            const res = await api(`/api/orchestrators/${name}/change-scope`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_scope: oldScope, new_scope: ns }),
            });
            close();
            await loadOrchestrators();
            selectOrchestrator(name, res.scope || ns);
        } catch (e) {
            errorEl.textContent = e.message;
            errorEl.classList.remove('hidden');
        }
    };

    const browseBtn = $('#change-scope-browse');
    const onBrowse = async () => {
        picker.innerHTML = '<div class="p-2 text-xs text-slate-500">Loading...</div>';
        picker.classList.remove('hidden');
        try {
            const projects = await api('/api/projects');
            picker.innerHTML = '';
            for (const p of projects) {
                const item = document.createElement('div');
                item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-slate-800 border-b border-slate-800/50';
                item.innerHTML = `<span class="text-white font-medium">${escHtml(p.name)}</span> <span class="text-slate-500 text-xs">${escHtml(p.path)}</span>`;
                item.addEventListener('click', () => { pathInput.value = p.path; picker.classList.add('hidden'); });
                picker.appendChild(item);
            }
        } catch { picker.innerHTML = '<div class="p-2 text-xs text-red-400">Failed to load</div>'; }
    };

    const cleanup = () => {
        document.removeEventListener('keydown', onKey);
        $('#change-scope-close').removeEventListener('click', closeHandler);
        $('#change-scope-cancel').removeEventListener('click', closeHandler);
        $('#change-scope-confirm').removeEventListener('click', confirmHandler);
        browseBtn.removeEventListener('click', onBrowse);
    };
    const closeHandler = () => { close(); cleanup(); };
    // doMove is async — cleanup only after successful close, not on error
    const confirmHandler = async () => { await doMove(); if (modal.classList.contains('hidden')) cleanup(); };
    const onKey = (e) => { if (e.key === 'Escape') { closeHandler(); } else if (e.key === 'Enter') { confirmHandler(); } };

    document.addEventListener('keydown', onKey);
    $('#change-scope-close').addEventListener('click', closeHandler);
    $('#change-scope-cancel').addEventListener('click', closeHandler);
    $('#change-scope-confirm').addEventListener('click', confirmHandler);
    browseBtn.addEventListener('click', onBrowse);
    modal.addEventListener('click', (e) => { if (e.target === modal) { close(); cleanup(); } }, { once: true });
}

function _updateHiddenBtn() {
    const btn = $('#hidden-tabs-btn');
    if (!btn) return;
    const hidden = _getHiddenTabs();
    const hasHidden = [...hidden].some(n => orchData.find(o => o.name === n));
    btn.classList.toggle('hidden', !hasHidden);
    if (hasHidden) btn.textContent = `👁 ${[...hidden].filter(n => orchData.find(o => o.name === n)).length}`;
}

function initHiddenTabsBtn() {
    const btn = $('#hidden-tabs-btn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const existing = document.getElementById('hidden-tabs-dropdown');
        if (existing) { existing.remove(); return; }
        const hidden = _getHiddenTabs();
        const items = [...hidden].filter(n => orchData.find(o => o.name === n));
        if (!items.length) return;
        const dd = document.createElement('div');
        dd.id = 'hidden-tabs-dropdown';
        const rect = btn.getBoundingClientRect();
        dd.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.bottom + 4}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:140px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
        for (const name of items) {
            const item = document.createElement('div');
            item.style.cssText = 'padding:6px 14px;font-size:12px;color:#94a3b8;cursor:pointer;white-space:nowrap';
            item.textContent = `👁 ${name.replace(/-orchestrator$/, '')}`;
            item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
            item.addEventListener('mouseleave', () => item.style.background = '');
            item.addEventListener('click', () => {
                const h = _getHiddenTabs(); h.delete(name); _setHiddenTabs(h);
                dd.remove();
                renderOrchTabs(orchData);
            });
            dd.appendChild(item);
        }
        document.body.appendChild(dd);
        const closeDd = (ev) => { if (!dd.contains(ev.target) && ev.target !== btn) { dd.remove(); document.removeEventListener('click', closeDd); } };
        setTimeout(() => document.addEventListener('click', closeDd), 0);
    });
    const tabsEl = $('#orch-tabs');
    if (tabsEl) {
        tabsEl.addEventListener('wheel', (e) => {
            e.preventDefault();
            tabsEl.scrollLeft += e.deltaY;
        }, { passive: false });
    }
}

function updateOrchTabDots() {
    const tabs = document.querySelectorAll('#orch-tabs .orch-tab');
    tabs.forEach(tab => {
        const scope = tab.title;
        const o = orchData.find(x => x.scope === scope);
        if (!o) return;
        const dot = tab.querySelector('.tab-dot');
        if (dot) dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : o.any_waiting ? '#f59e0b' : '#eab308';
        const existing = tab.querySelector('.tab-unread');
        if (_unreadTabs.has(scope) && !existing) {
            const unread = document.createElement('span');
            unread.className = 'tab-unread';
            unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
            tab.appendChild(unread);
        } else if (!_unreadTabs.has(scope) && existing) {
            existing.remove();
        }
    });
}

function selectOrchestrator(name, scope) {
    _unreadTabs.delete(scope);
    const picker = $('#orch-picker');
    picker.value = scope;
    const opt = [...picker.options].find(o => o.dataset.name === name);
    if (opt) picker.selectedIndex = opt.index;

    // Keep last 10 recently used orchestrators — used to sort tabs on next load
    const recent = JSON.parse(localStorage.getItem('recentOrchs') || '[]');
    const filtered = recent.filter(n => n !== name);
    filtered.unshift(name);
    localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));

    onOrchestratorChange();
    renderOrchTabs(orchData);
}

async function onOrchestratorChange() {
    saveDraft();
    if (eventSource) { eventSource.close(); eventSource = null; }
    const picker = $('#orch-picker');
    const opt = picker.selectedOptions[0];
    currentScope = picker.value || null;
    chatLogs = {};
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    _finalizedBubble = null;
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    selectedAgent = opt?.dataset?.name || null;
    if (currentScope && selectedAgent) {
        localStorage.setItem('lastOrchScope', currentScope);
        localStorage.setItem('lastOrchName', selectedAgent);
    }
    $('#chat').innerHTML = '';
    scrollAfterLoad = true;
    updateAgentInfo(null);
    updateInputState();
    restoreDraft();
    await refreshSessions(); connectSSE(); initFilePanel();
    if (_tasksTabActive) loadTasks();
    if (_jobsTabActive) loadJobs();
}

// === Agent Selection ===
async function selectAgent(name) {
    saveDraft();
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    _finalizedBubble = null;
    selectedAgent = name;
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    $('#chat').innerHTML = '';
    chatLogs[name] = { lastId: 0, firstId: null, initialCount: 0 };
    scrollAfterLoad = true;
    updateInputState();
    restoreDraft();
    renderAgentList();
    fetchAgentContext(name);
    await refreshSessions();
    connectSSE();
}

function updateInputState() {
    const input = $('#chat-input');
    const btn = $('#send-btn');
    if (!selectedAgent) {
        input.placeholder = 'Message...';
        input.disabled = false;
        btn.disabled = false;
        return;
    }
    const sessions = [...document.querySelectorAll('.agent-item')];
    const agentEl = sessions.find(el => {
        const nameEl = el.querySelector('.text-xs.font-medium');
        return nameEl && nameEl.textContent === selectedAgent;
    });
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
        const data = await api('/api/models');
        const models = data.models || [];
        _MODELS = models.map(m => ({ id: m.id, label: m.name }));
        _modelsLoaded = true;
    } catch {}
}
function _updateProxyStatus(connected) {
    const el = document.getElementById('proxy-status');
    if (!el) return;
    if (connected) {
        el.textContent = '🟢';
        el.title = 'Proxy connected';
    } else {
        el.textContent = '🔴';
        el.title = 'Proxy offline — no models available';
    }
}
async function _showModelPicker(agentName, currentModel, anchor) {
    const existing = document.getElementById('model-picker-dd');
    if (existing) { existing.remove(); return; }
    await _ensureModels();
    if (!_MODELS.length) { console.warn('No models available for picker'); return; }
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
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                dd.remove();
                try {
                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
                    if (resp && !resp.error) {
                        $('#ai-model').textContent = m.id;
                        loadSessions();
                    }
                } catch (e) { console.warn('Change model failed:', e); }
            });
        }
        dd.appendChild(item);
    }
    document.body.appendChild(dd);
    const close = (e) => { if (!dd.contains(e.target) && e.target !== anchor) { dd.remove(); document.removeEventListener('click', close); } };
    setTimeout(() => document.addEventListener('click', close), 10);
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
        $('#subagents-btn')?.classList.add('hidden');
        $('#compact-btn').classList.add('hidden');
        $('#restart-cli-btn').classList.add('hidden');
        return;
    }
    $('#view-prompt-btn').classList.remove('hidden');
    $('#subagents-btn')?.classList.remove('hidden');
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
        changeBtn.addEventListener('mouseenter', () => changeBtn.style.color = '#94a3b8');
        changeBtn.addEventListener('mouseleave', () => changeBtn.style.color = '#475569');
        modelEl.parentElement.appendChild(changeBtn);
    }
    // Model can only be changed when the CLI is not actively processing — changing mid-turn would be ignored by the SDK
    const isIdle = session.status === 'idle' || session.status === 'stopped' || session.status === 'waiting';
    changeBtn.style.display = isIdle ? 'inline' : 'none';
    changeBtn.onclick = () => _showModelPicker(session.name, session.model, changeBtn);
    $('#ai-role').textContent = session.role || 'worker';
    // Cost is virtual (API-equivalent), not real spend — subscription model
    $('#ai-cost').textContent = fmtCost(session.cost_usd);
    $('#ai-cost').title = `$${(session.cost_usd || 0).toFixed(4)} (CLI cost, includes cache)`;
    $('#ai-branch').textContent = session.branch || '-';
    $('#ai-scope').textContent = session.scope || '-';
    const descEl = $('#ai-desc'); const descLabel = $('#ai-desc-label');
    if (descEl && descLabel) {
        if (session.description) { descEl.textContent = session.description; descEl.title = session.description; descEl.classList.remove('hidden'); descLabel.classList.remove('hidden'); }
        else { descEl.classList.add('hidden'); descLabel.classList.add('hidden'); }
    }
    let progEl = $('#ai-progress'); let progLabel = $('#ai-progress-label');
    if (!progEl) {
        const grid = document.querySelector('#agent-info .grid');
        if (grid) {
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
    const max = ctx.max_tokens || 0;
    const totalK = total > 1000 ? `${(total/1000).toFixed(0)}k` : total;
    const maxK = max > 1000 ? `${(max/1000).toFixed(0)}k` : max;
    let s = `${pct}% (${totalK}/${maxK})`;
    if (ctx.cache_hit !== undefined) s += ` · cache ${Number(ctx.cache_hit).toFixed(2)}%`;
    return s;
}

async function fetchAgentContext(name) {
    if (!currentScope) return;
    try {
        const ctx = await api(`/api/sessions/${name}/context?scope=${encodeURIComponent(currentScope)}`);
        const text = formatContext(ctx);
        contextCache[`${currentScope}:${name}`] = text;
        if (name === selectedAgent) setContextDisplay(text);
    } catch {}
}

// === Agent List ===
function renderAgentList(sessions) {
    if (!sessions) return;
    const list = $('#agent-list');
    list.innerHTML = '';

    for (const s of sessions) {
        if (s.color) agentColors[s.name] = s.color;
    }

    const byName = new Map();
    for (const s of sessions) byName.set(s.name, s);

    const childrenMap = new Map();
    const roots = [];
    for (const s of sessions) {
        const pn = s.parent_name || '';
        if (pn && byName.has(pn)) {
            if (!childrenMap.has(pn)) childrenMap.set(pn, []);
            childrenMap.get(pn).push(s);
        } else {
            roots.push(s);
        }
    }

    // Guard against cycles in the parent/child graph — shouldn't happen but the data comes from DB
    const seen = new Set();
    const buildNode = (session, isChild, isLast) => {
        if (seen.has(session.name)) return null;
        seen.add(session.name);
        const wrapper = document.createElement('div');
        wrapper.className = 'tree-node' + (isChild ? ' tree-child' : '') + (isLast ? ' tree-last' : '');
        wrapper.appendChild(createAgentItem(session));
        const kids = childrenMap.get(session.name) || [];
        if (kids.length > 0) {
            const childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            for (let i = 0; i < kids.length; i++) {
                const childNode = buildNode(kids[i], true, i === kids.length - 1);
                if (childNode) childContainer.appendChild(childNode);
            }
            wrapper.appendChild(childContainer);
        }
        return wrapper;
    };
    for (const r of roots) {
        const node = buildNode(r, false, false);
        if (node) list.appendChild(node);
    }
    for (const s of sessions) {
        if (!seen.has(s.name)) {
            seen.add(s.name);
            const node = buildNode(s, false, false);
            if (node) list.appendChild(node);
        }
    }
}

// Static defaults — server may extend these with custom pipeline roles at startup
let _roleIcons = {'orchestrator':'👑','worker':'⚙️','full-cycle':'🔄','sub-orchestrator':'🎯','reviewer':'🔍','watcher':'👁️'};
fetch('/api/role-icons').then(r=>r.json()).then(d=>{_roleIcons={..._roleIcons,...d}}).catch(()=>{});

function createAgentItem(s) {
    const isSelected = s.name === selectedAgent;
    const isDead = s.status === 'stopped' || s.status === 'error';
    const item = document.createElement('div');
    item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isSelected ? 'bg-indigo-900/30 border border-indigo-500/30' :
        isDead ? 'opacity-50 hover:opacity-70' : 'hover:bg-slate-800/50'
    }`;
    item.addEventListener('click', () => selectAgent(s.name));
    if (s.id) item.dataset.sessionId = s.id;

    if (s.color) item.style.borderLeft = `3px solid ${s.color}`;

    const icon = document.createElement('span');
    const roleKey = s.role || (s.is_orchestrator ? 'orchestrator' : 'worker');
    icon.textContent = isDead ? '🪦' : (_roleIcons[roleKey] || '⚙️');
    icon.className = 'text-sm';

    const info = document.createElement('div');
    info.className = 'flex-1 min-w-0';
    const nameRow = document.createElement('div');
    nameRow.className = 'flex items-center justify-between';
    const nameEl = document.createElement('span');
    nameEl.className = 'text-xs font-medium truncate';
    nameEl.textContent = s.name;
    const statusEl = document.createElement('span');
    const statusColors = {running: '#22c55e', idle: '#eab308', waiting: '#f59e0b'};
    const statusBgs = {running: 'rgba(34,197,94,0.15)', idle: 'rgba(234,179,8,0.12)', waiting: 'rgba(245,158,11,0.15)'};
    const statusIcons = {running: '⚡', idle: '☕️', waiting: '⏳'};
    statusEl.className = 'text-xs font-mono font-bold shrink-0';
    statusEl.style.color = statusColors[s.status] || '#6b7280';
    statusEl.style.backgroundColor = statusBgs[s.status] || 'rgba(107,114,128,0.1)';
    statusEl.style.padding = '1px 6px';
    statusEl.style.borderRadius = '4px';
    statusEl.textContent = `${statusIcons[s.status] || '●'} ${s.status}`;
    nameRow.append(nameEl, statusEl);

    const meta = document.createElement('div');
    meta.className = 'text-xs text-slate-600 mt-0.5 flex justify-between';
    const modelSpan = document.createElement('span');
    modelSpan.textContent = s.model || '';
    meta.appendChild(modelSpan);
    if (s.cost_usd > 0) {
        const costSpan = document.createElement('span');
        costSpan.className = 'text-green-400';
        costSpan.textContent = fmtCost(s.cost_usd);
        costSpan.title = fmtCost(s.cost_usd);
        meta.appendChild(costSpan);
    }

    info.append(nameRow, meta);

    const pct = s.context_pct || 0;
    if (pct > 0) {
        const bar = document.createElement('div');
        bar.className = 'w-full h-1 bg-slate-800 rounded-full mt-1';
        const fill = document.createElement('div');
        fill.className = 'h-1 rounded-full transition-all';
        fill.style.width = `${Math.min(pct, 100)}%`;
        fill.style.backgroundColor = pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#22c55e';
        fill.title = `${pct}% context`;
        bar.appendChild(fill);
        info.appendChild(bar);
    }
    const ppct = s.progress_pct || 0;
    if (ppct > 0) {
        const pbar = document.createElement('div');
        pbar.className = 'w-full h-1 bg-slate-800 rounded-full mt-1';
        const pfill = document.createElement('div');
        pfill.className = 'h-1 rounded-full transition-all';
        pfill.style.width = `${Math.min(ppct, 100)}%`;
        pfill.style.backgroundColor = '#818cf8';
        pfill.title = `${ppct}% progress`;
        pbar.appendChild(pfill);
        info.appendChild(pbar);
        if (s.progress_status) {
            const ptext = document.createElement('div');
            ptext.style.cssText = 'font-size:9px;color:#64748b;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
            ptext.textContent = `${ppct}% — ${s.progress_status}`;
            info.appendChild(ptext);
        }
    }
    item.append(icon, info);

    item.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        _showAgentContextMenu(e, s);
    });

    if (isSelected) updateAgentInfo(s);
    return item;
}

let _agentCtxMenu = null;
function _showAgentContextMenu(e, s) {
    if (_agentCtxMenu) _agentCtxMenu.remove();
    const menu = document.createElement('div');
    _agentCtxMenu = menu;
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
    const close = () => { if (_agentCtxMenu) { _agentCtxMenu.remove(); _agentCtxMenu = null; } };
    document.addEventListener('click', close, { once: true });

    const mkItem = (label, color, fn) => {
        const item = document.createElement('div');
        item.style.cssText = `padding:6px 14px;font-size:12px;color:${color};cursor:pointer;white-space:nowrap`;
        item.textContent = label;
        item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
        item.addEventListener('mouseleave', () => item.style.background = '');
        item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
        return item;
    };

    const tgEnabled = s.tg_topic;
    menu.appendChild(mkItem(
        tgEnabled ? '📌 TG Topic: ON → OFF' : '📌 TG Topic: OFF → ON',
        tgEnabled ? '#f59e0b' : '#94a3b8',
        async () => {
            try {
                await api(`/api/sessions/${s.name}/tg-topic?scope=${encodeURIComponent(currentScope)}&enabled=${!tgEnabled}`, { method: 'PATCH' });
                await refreshSessions();
            } catch (e) { console.error('TG topic toggle failed:', e); }
        }
    ));

    document.body.appendChild(menu);
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
}

// === Chat ===
// Optimistic UI: show message immediately, debounce actual send so rapid
// follow-up messages get batched. The server echoes back via SSE which
// replaces the bubble with the canonical version.
async function sendChat() {
    const input = $('#chat-input');
    const msg = input.value.trim();
    if (!msg || !currentScope || !selectedAgent) return;
    input.value = '';
    clearPastePreview();

    pendingUserMsgs.push(msg);
    localMessages.add(msg);
    showPendingBubble();

    if (uiDebounceTimer) clearTimeout(uiDebounceTimer);
    uiDebounceTimer = setTimeout(() => finalizePending(), UI_DEBOUNCE_MS);

    try {
        await api(`/api/sessions/${selectedAgent}/send`, {
            method: 'POST',
            body: JSON.stringify({ message: msg, scope: currentScope }),
            signal: AbortSignal.timeout(15000),
        });
    } catch (e) {
        if (e.name === 'TimeoutError') return;
        if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
        if (pendingBubble) { const ring = pendingBubble.querySelector('.debounce-ring'); if (ring) ring.remove(); }
        pendingBubble = null; pendingUserMsgs = []; _finalizedBubble = null;
        removeWaitingIndicator();
        addChatEntry('error', e.message);
    }
}

function showPendingBubble() {
    const chat = $('#chat');
    if (!pendingBubble) {
        pendingBubble = document.createElement('div');
        pendingBubble.className = 'chat-user ml-16 px-3 py-2 rounded-lg text-sm break-words';
        chat.appendChild(pendingBubble);
    }
    pendingBubble.textContent = pendingUserMsgs.join('\n');
    const oldRing = pendingBubble.querySelector('.debounce-ring');
    if (oldRing) oldRing.remove();
    const ring = document.createElement('span');
    ring.className = 'debounce-ring';
    pendingBubble.appendChild(ring);
    chat.scrollTop = chat.scrollHeight;
}

let _finalizedBubble = null;
function finalizePending() {
    if (!pendingBubble) return;
    const ring = pendingBubble.querySelector('.debounce-ring');
    if (ring) ring.remove();
    const combined = pendingUserMsgs.join('\n');
    localMessages.add(combined);
    _finalizedBubble = pendingBubble;
    pendingBubble = null;
    pendingUserMsgs = [];
    uiDebounceTimer = null;
    showWaitingIndicator();
}

function showWaitingIndicator() {
    removeWaitingIndicator();
    const chat = $('#chat');
    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    const div = document.createElement('div');
    div.id = 'waiting-indicator';
    div.className = 'flex items-center gap-2 text-xs text-slate-500 py-2 px-3';
    div.innerHTML = '<span class="waiting-dots"><span>.</span><span>.</span><span>.</span></span> waiting for response';
    chat.appendChild(div);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

let pastedImages = [];

async function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
        if (!item.type.startsWith('image/')) continue;
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;
        const input = $('#chat-input');
        const oldText = input.value;
        input.value = oldText + (oldText ? '\n' : '') + '⏳ uploading image...';
        const formData = new FormData();
        formData.append('file', file, `paste-${Date.now()}.png`);
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.path) {
                pastedImages.push(data.url);
                input.value = oldText + (oldText ? '\n' : '') + data.path;
                showImagePreview(data.url, data.path);
            }
        } catch (err) {
            input.value = oldText;
        }
        input.focus();
        break;
    }
}

function showImagePreview(url, filePath) {
    let container = $('#paste-preview');
    if (!container) {
        container = document.createElement('div');
        container.id = 'paste-preview';
        container.className = 'flex flex-wrap gap-2 px-1 pb-1';
        const inputRow = $('#chat-input').parentElement;
        inputRow.parentElement.insertBefore(container, inputRow);
    }
    const wrap = document.createElement('div');
    wrap.className = 'relative';
    wrap.dataset.url = url;
    wrap.dataset.filePath = filePath || url;
    const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(filePath || url);
    if (isImage) {
        const img = document.createElement('img');
        img.src = url;
        img.className = 'h-16 rounded border border-slate-700';
        img.loading = 'lazy';
        img.style.cursor = 'pointer';
        img.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(img);
    } else {
        const name = (filePath || url).split('/').pop();
        const chip = document.createElement('div');
        chip.className = 'flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-xs text-slate-400 cursor-pointer hover:border-indigo-500';
        chip.style.maxWidth = '180px';
        chip.innerHTML = `<span>📄</span><span class="truncate">${DOMPurify.sanitize(name)}</span>`;
        chip.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(chip);
    }
    const rm = document.createElement('button');
    rm.className = 'absolute -top-1 -right-1 bg-red-600 text-white rounded-full w-4 h-4 text-xs leading-none';
    rm.textContent = '×';
    rm.addEventListener('click', () => {
        wrap.remove();
        pastedImages = pastedImages.filter(u => u !== url);
        const input = $('#chat-input');
        const removePath = filePath || url;
        input.value = input.value.split('\n').filter(line => line.trim() !== removePath.trim()).join('\n').trim();
        if (!container.children.length) container.remove();
    });
    wrap.appendChild(rm);
    container.appendChild(wrap);
}

function clearPastePreview() {
    pastedImages = [];
    const el = $('#paste-preview');
    if (el) el.remove();
}


function renderImages(el, content) {
    const re = /(\/\S+\.(png|jpg|jpeg|gif|webp|svg))/gi;
    const matches = content.match(re);
    if (!matches) return;
    for (const path of matches) {
        const url = `/api/files/raw?path=${encodeURIComponent(path)}`;
        const img = document.createElement('img');
        img.src = url;
        img.loading = 'lazy';
        img.style.cssText = 'max-height:200px;border-radius:8px;cursor:pointer;margin-top:6px;display:block';
        img.onerror = () => img.remove();
        img.addEventListener('click', () => openImageLightbox(url));
        el.appendChild(img);
    }
}

function removeWaitingIndicator() {
    const el = $('#waiting-indicator');
    if (el) el.remove();
}

async function stopAgent() {
    if (!selectedAgent || !currentScope) return;
    try {
        await api(`/api/sessions/${selectedAgent}/interrupt`, {
            method: 'POST',
            body: JSON.stringify({ scope: currentScope }),
        });
    } catch {}
}

function updateStopButton(status) {
    const btn = $('#stop-btn');
    if (status === 'running') {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

function _showImageOverlay(src) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer';
    const bigImg = document.createElement('img');
    bigImg.src = src;
    bigImg.style.cssText = 'max-width:90vw;max-height:90vh;object-fit:contain';
    overlay.appendChild(bigImg);
    overlay.addEventListener('click', () => overlay.remove());
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(overlay);
}

function addTimestamp(el, ts) {
    if (!el || !ts || el.querySelector('.chat-time')) return;
    const d = new Date(ts);
    const local = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const time = document.createElement('span');
    time.className = 'chat-time';
    time.textContent = local;
    el.appendChild(time);
}

function addCopyBtn(el, text) {
    if (!el || el.querySelector('.copy-btn')) return;
    el.style.position = 'relative';
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = '📋';
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // navigator.clipboard requires HTTPS — fallback for HTTP
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement('textarea');
            ta.value = text; ta.style.cssText = 'position:fixed;left:-9999px';
            document.body.appendChild(ta); ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        btn.textContent = '✅';
        setTimeout(() => btn.textContent = '📋', 1500);
    });
    el.appendChild(btn);
}

let streamBubble = null;
let streamContent = '';
let streamPending = '';
let _streamRafId = null;
let _streamLastParse = 0;
const _STREAM_BASE_CPS = 12;  // chars per frame at 60fps (~720 chars/sec)
const _STREAM_PARSE_INTERVAL = 50;  // ms between marked.parse calls

function _streamRenderTick() {
    _streamRafId = null;
    if (!streamBubble || !streamPending) return;
    // Adaptive speed: if buffer is growing, accelerate to not fall behind
    const chunkSize = Math.max(_STREAM_BASE_CPS, Math.floor(streamPending.length / 8));
    const chunk = streamPending.slice(0, chunkSize);
    streamPending = streamPending.slice(chunkSize);
    streamContent += chunk;
    const now = performance.now();
    const sinceLastParse = now - _streamLastParse;
    if (sinceLastParse >= _STREAM_PARSE_INTERVAL || !streamPending) {
        _streamLastParse = now;
        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
    }
    // Typing cursor — remove stale one before adding
    const oldCur = streamBubble.querySelector('.typing-cursor');
    if (oldCur) oldCur.remove();
    const lastEl = streamBubble.querySelector(':scope > :last-child') || streamBubble;
    const cur = document.createElement('span');
    cur.className = 'typing-cursor';
    cur.textContent = '▍';
    lastEl.appendChild(cur);
    const chat = $('#chat');
    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    if (wasAtBottom) chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
    if (streamPending) _streamRafId = requestAnimationFrame(_streamRenderTick);
}

function _streamFlush() {
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    if (streamPending) {
        streamContent += streamPending;
        streamPending = '';
    }
}

function _renderJsonGrid(obj, container, maxDepth) {
    if (maxDepth === undefined) maxDepth = 2;
    const grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px;align-items:baseline';
    const entries = Object.entries(obj);
    for (const [key, val] of entries) {
        if (key === 'system_prompt' || key === 'error_trace') continue;
        const keyEl = document.createElement('span');
        keyEl.style.cssText = 'color:#64748b;white-space:nowrap;font-family:monospace';
        keyEl.textContent = key;
        grid.appendChild(keyEl);
        const valEl = document.createElement('span');
        valEl.style.cssText = 'overflow:hidden;text-overflow:ellipsis;overflow-wrap:anywhere;min-width:0';
        if (val === null || val === undefined) {
            valEl.textContent = 'null';
            valEl.style.color = '#6b7280';
        } else if (typeof val === 'boolean') {
            valEl.textContent = String(val);
            valEl.style.color = val ? '#22c55e' : '#ef4444';
        } else if (typeof val === 'number') {
            valEl.textContent = String(val);
            valEl.style.color = '#eab308';
        } else if (typeof val === 'string') {
            const MAX_STR = 150;
            const short = val.length > MAX_STR ? val.slice(0, MAX_STR) + '…' : val;
            valEl.textContent = short;
            valEl.style.color = '#cbd5e1';
            if (val.length > MAX_STR) {
                valEl.style.cursor = 'pointer';
                valEl.title = 'Click to expand';
                let _strExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _strExp = !_strExp;
                    valEl.textContent = _strExp ? val : short;
                });
            }
        } else if (Array.isArray(val)) {
            if (val.length === 0) {
                valEl.textContent = '[]';
                valEl.style.color = '#6b7280';
            } else if (val.every(v => typeof v === 'string' || typeof v === 'number')) {
                const arrStr = val.join(', ');
                valEl.textContent = arrStr.length > 120 ? arrStr.slice(0, 120) + '…' : arrStr;
                valEl.style.color = '#cbd5e1';
            } else {
                valEl.textContent = `[${val.length} items]`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _arrExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _arrExp = !_arrExp;
                    if (_arrExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `[${val.length} items]`;
                    }
                });
            }
        } else if (typeof val === 'object' && maxDepth > 0) {
            const subKeys = Object.keys(val);
            if (subKeys.length <= 4) {
                const sub = document.createElement('div');
                _renderJsonGrid(val, sub, maxDepth - 1);
                valEl.textContent = '';
                valEl.appendChild(sub);
            } else {
                valEl.textContent = `{${subKeys.length} keys}`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _objExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _objExp = !_objExp;
                    if (_objExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `{${subKeys.length} keys}`;
                    }
                });
            }
        } else {
            valEl.textContent = JSON.stringify(val);
            valEl.style.color = '#94a3b8';
        }
        grid.appendChild(valEl);
    }
    container.appendChild(grid);
    return grid;
}

function buildCompactToolLine(type, content, ts) {
    const line = document.createElement('div');
    line.className = 'flex items-center gap-2 text-xs py-0.5 px-2 cursor-pointer rounded group';
    line.style.color = '#64748b';

    if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30);
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        const icon = toolIcon(rawName);
        const short = toolShortName(rawName);

        let preview = body;
        try {
            const parsed = JSON.parse(body);
            if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${({'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-6[1m]':'Opus 1M','claude-opus-4-6':'Opus','claude-sonnet-4-6':'Sonnet','claude-haiku-4-5':'Haiku'})[parsed.model || 'claude-sonnet-4-6'] || parsed.model || 'Sonnet'})`;
            else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = `🌐 "${parsed.query || ''}"`;
            else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
            else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
            else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
            else if (rawName === 'mcp__orchestra__kill_worker') preview = `💀 Kill: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__stop_worker') preview = `⏸️ Stop: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__get_worker_logs') preview = `📋 Logs: ${parsed.name || '?'} (${parsed.limit || 20})`;
            else if (rawName === 'mcp__orchestra__get_worker_info') preview = `🤖 Info: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__list_agents') preview = '🎼 Agents';
            else if (rawName === 'mcp__orchestra__list_orchestrators') preview = '🎯 Orchestrators';
            else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__list_jobs') preview = '📊 Jobs';
            else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
            else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
            else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
            else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
            else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
            else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
            else if (rawName === 'mcp__orchestra__task_create') { const _pp = {0:'🔴',1:'🟠',3:'🟢'}[parsed.priority]||''; preview = `📋 New: ${_pp}"${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+' ${CUR}' : ''}`; }
            else if (rawName === 'mcp__orchestra__task_update') { const _f = Object.keys(parsed).filter(k=>k!=='par').map(k=>`${k}→${parsed[k]}`).join(', '); preview = `✏️ #${taskNum(parsed.par) || '?'}: ${_f}`; }
            else if (rawName === 'mcp__orchestra__task_list') { const _fl = [parsed.status,parsed.project,parsed.assignee].filter(Boolean).join(', '); preview = `📋 Tasks${_fl ? ' ('+_fl+')' : ''}`; }
            else if (rawName === 'mcp__orchestra__task_get') preview = `📋 #${taskNum(parsed.par) || '?'}`;
            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'} ${CUR}`;
            else if (rawName === 'mcp__orchestra__payment_status') preview = '💰 Balance';
            else if (rawName === 'mcp__orchestra__bg_create') { const _bi = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
            else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
            else if (rawName === 'mcp__orchestra__bg_cancel') preview = `⏹ Cancel job ${(parsed.job_id||'').slice(0,8)}`;
            else if (rawName.startsWith('mcp__yougile__')) { const yn = rawName.replace('mcp__yougile__',''); preview = `📋 ${yn}${parsed.title ? ': '+parsed.title : ''}`; }
            else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') { let _d = '?'; try { _d = new URL(parsed.url).hostname; } catch {} preview = `🌐 ${_d}`; }
            else if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
            else if (parsed.command) preview = parsed.command;
            else if (parsed.pattern) preview = parsed.pattern;
            else if (parsed.path) preview = parsed.path;
            else if (parsed.message) preview = parsed.message;
            else if (parsed.content) preview = parsed.content.slice(0, 80);
            else preview = body.slice(0, 80);
        } catch { preview = body.slice(0, 120); }

        const isOrch = rawName.startsWith('mcp__orchestra__');
        const nameColor = isOrch ? '#a78bfa' : '#38bdf8';

        const iconSpan = document.createElement('span');
        iconSpan.textContent = icon;
        iconSpan.style.minWidth = '1.2em';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = short;
        nameSpan.style.color = nameColor;
        nameSpan.style.minWidth = 'max-content';

        let desc = '';
        try { desc = JSON.parse(body).description || ''; } catch {}

        const descSpan = document.createElement('span');
        descSpan.className = 'shrink-0';
        descSpan.style.color = '#64748b';
        descSpan.textContent = desc ? `— ${desc}` : '';

        const previewSpan = document.createElement('span');
        previewSpan.className = 'truncate flex-1 opacity-60';
        previewSpan.textContent = preview;

        const resultSpan = document.createElement('span');
        resultSpan.className = 'compact-result shrink-0';
        resultSpan.style.color = '#475569';

        line.append(iconSpan, nameSpan, descSpan, previewSpan, resultSpan);
        line.dataset.compactTool = '1';
        line.dataset.toolContent = content;
        line.dataset.toolRaw = rawName;

        line.addEventListener('mouseenter', () => line.style.backgroundColor = 'rgba(30,41,59,0.5)');
        line.addEventListener('mouseleave', () => line.style.backgroundColor = '');

        let fullBubble = null;
        line.addEventListener('click', () => {
            if (fullBubble) {
                fullBubble.remove();
                fullBubble = null;
                return;
            }
            fullBubble = document.createElement('div');
            fullBubble.className = 'ml-4 mb-1';
            const tempContent = line.dataset.toolContent;
            const tempResult = line.dataset.resultContent || '';
            const savedCompact = window.compactMode;
            window.compactMode = false;
            const anchor = line.nextSibling;
            const chat = $('#chat');
            const sentinel = document.createElement('span');
            sentinel.style.display = 'none';
            if (anchor) chat.insertBefore(sentinel, anchor);
            else chat.appendChild(sentinel);
            addChatEntry('tool', tempContent, null, sentinel);
            if (tempResult) {
                addChatEntry('tool_result', tempResult, null, sentinel);
            }
            window.compactMode = savedCompact;
            const rendered = [];
            let node = line.nextSibling;
            while (node && node !== sentinel) {
                rendered.push(node);
                node = node.nextSibling;
            }
            sentinel.remove();
            for (const el of rendered) {
                el.remove();
                fullBubble.appendChild(el);
            }
            line.after(fullBubble);
        });
    } else {
        line.textContent = '📎 ' + content.slice(0, 100);
    }

    return line;
}

function _findLastBefore(parent, selector, anchor) {
    let node = anchor ? anchor.previousElementSibling : parent.lastElementChild;
    while (node) {
        if (node.matches(selector)) return node;
        node = node.previousElementSibling;
    }
    return null;
}

const HIDE_THINKING = document.body.dataset.hideThinking === 'true';

// Append a live sub-agent log line into its accordion body. If the accordion
// isn't there yet (race: stream before start), no-op — the sub-agent block owns
// its own rendering; live lines are best-effort decoration.
function appendSubagentLog(subId, evType, content) {
    const chat = $('#chat');
    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
    if (!host) return;
    const body = host.querySelector('.sa-body');
    if (!body) return;
    if (evType === 'stream') {
        // Coalesce contiguous stream text into one line (typewriter feel)
        let last = body.lastElementChild;
        if (last && last.classList.contains('sa-stream')) {
            last.textContent += content;
        } else {
            last = document.createElement('div');
            last.className = 'sa-stream';
            last.textContent = content;
            body.appendChild(last);
        }
    } else {
        const line = document.createElement('div');
        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
        line.textContent = `${icon} ${short}`;
        body.appendChild(line);
    }
    body.scrollTop = body.scrollHeight;
}

// Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
// anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
// payload = full SSE log object (carries subagent_id for sub-agent nesting)
function addChatEntry(type, content, ts, anchor, payload) {
    if (HIDE_THINKING && type === 'thinking') return;
    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
        return;
    }
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');
    let _insertedBeforeStream = false;
    const _insert = (el) => {
        if (anchor) return chat.insertBefore(el, anchor);
        if (streamBubble && streamBubble.parentNode === chat) {
            _insertedBeforeStream = true;
            return chat.insertBefore(el, streamBubble);
        }
        chat.appendChild(el);
    };

    // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
    const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);

    if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
        const div = document.createElement('div');
        div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
        const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
        if (b64Match) {
            const img = document.createElement('img');
            img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;cursor:pointer';
            img.addEventListener('click', () => _showImageOverlay(img.src));
            div.appendChild(img);
        } else {
            div.textContent = '🖼 [Image]';
            div.style.color = '#64748b';
        }
        addTimestamp(div, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(div);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (window.compactMode && (type === 'tool' || type === 'tool_result')) {
        if (type === 'tool_result') {
            const lastC = _findLastBefore(chat, '[data-compact-tool]', anchor);
            if (lastC && _isBase64Image) {
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan) resultSpan.textContent = '🖼 image';
                lastC.dataset.resultContent = '[image]';
                return;
            }
            if (lastC) {
                const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
                const rawName = lastC.dataset.toolRaw || '';
                const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
                const isReadTool = rawName === 'Read';
                const isToolSearch = rawName === 'ToolSearch';
                const isBugReportCompact = rawName === 'mcp__orchestra__report_bug';
                const isSendFileCompact = rawName === 'mcp__orchestra__send_file';
                const isOrchSimpleCompact = ['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__compact_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__update_worker_description','mcp__orchestra__merge_worker','mcp__orchestra__send_message','mcp__orchestra__list_agents','mcp__orchestra__list_orchestrators','mcp__orchestra__list_jobs','mcp__orchestra__get_worker_logs','mcp__orchestra__get_worker_info','mcp__orchestra__bg_create','mcp__orchestra__bg_cancel','mcp__orchestra__update_progress'].includes(rawName);
                const isGlobCompact = rawName === 'Glob';
                const isSkillCompact = rawName === 'Skill';
                const isYougileCompact = rawName.startsWith('mcp__yougile__');
                const isWebFetchCompact = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
                const isWebSearchCompact = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan && isSendFileCompact) {
                    resultSpan.textContent = clean.includes('error') ? '❌' : '✅ sent';
                } else if (resultSpan && isOrchSimpleCompact) {
                    const hasErr = clean.includes('error') || clean.includes('Error') || clean.includes('fail') || clean.includes('Fail');
                    if (rawName === 'mcp__orchestra__update_progress') { resultSpan.textContent = '✓'; resultSpan.style.color = '#818cf8'; }
                    else if (['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__update_worker_description','mcp__orchestra__merge_worker','mcp__orchestra__bg_create'].includes(rawName)) resultSpan.textContent = hasErr ? '❌' : '✅';
                    else if (rawName === 'mcp__orchestra__send_message') { const m = clean.match(/sent to '(.+?)'/i); resultSpan.textContent = hasErr ? '❌' : m ? `✅ → ${m[1]}` : '✅'; }
                    else if (rawName === 'mcp__orchestra__bg_cancel') resultSpan.textContent = hasErr ? '❌' : '⏹';
                    else if (rawName === 'mcp__orchestra__compact_worker') { const m = clean.match(/(\d+)%/); resultSpan.textContent = m ? `✅ ${m[1]}%` : '✅'; }
                    else if (rawName === 'mcp__orchestra__get_worker_info') { try { const d = JSON.parse(clean); resultSpan.textContent = `${d.status === 'running' ? '🟢' : d.status === 'idle' ? '🟡' : '⚪'} ${d.name || '?'}`; } catch { resultSpan.textContent = '✅'; } }
                    else { const ct = clean.split('\n').filter(l=>l.trim()).length; resultSpan.textContent = `📎 ${ct} items`; }
                } else if (resultSpan && isGlobCompact) {
                    const ct = clean.split('\n').filter(l=>l.trim()).length;
                    resultSpan.textContent = `📎 ${ct} files`;
                } else if (resultSpan && (isSkillCompact || isYougileCompact)) {
                    resultSpan.textContent = clean.includes('error') ? '❌' : '✅';
                } else if (resultSpan && isWebFetchCompact) {
                    const short = clean.length > 40 ? clean.replace(/\n/g, ' ').slice(0, 40) + '…' : clean.replace(/\n/g, ' ');
                    resultSpan.textContent = '📎 ' + short;
                } else if (resultSpan && isBugReportCompact) {
                    resultSpan.textContent = '✅ reported';
                } else if (resultSpan && isToolSearch) {
                    let toolName = '';
                    try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
                    if (!toolName) { const m = clean.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
                    resultSpan.textContent = toolName ? `✅ ${toolName}` : '✅ loaded';
                } else if (resultSpan && isWebSearchCompact) {
                    resultSpan.textContent = '✅ results';
                } else if (resultSpan && !isEditTool && !isReadTool) {
                    const short = clean.length > 40 ? clean.slice(0, 40).replace(/\n/g, ' ') + '…' : clean.replace(/\n/g, ' ');
                    resultSpan.textContent = '📎 ' + short;
                } else if (resultSpan && isEditTool) {
                    resultSpan.textContent = '📎 updated';
                } else if (resultSpan && isReadTool) {
                    let readShort = 'OK';
                    try {
                        const colonIdx = lastC.dataset.toolContent.indexOf(':');
                        const bd = colonIdx > 0 ? lastC.dataset.toolContent.slice(colonIdx + 1).trim() : '';
                        const parsed = JSON.parse(bd);
                        if (parsed.file_path) readShort = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || parsed.file_path;
                    } catch {}
                    resultSpan.textContent = '📖 ' + readShort;
                }
                lastC.dataset.resultContent = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
                return;
            }
        }
        const line = buildCompactToolLine(type, content, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(line);
        // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
        while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    // Stream events feed the typewriter buffer — RAF loop renders incrementally
    if (type === 'stream') {
        removeWaitingIndicator();
        if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
        if (!streamBubble) {
            streamBubble = document.createElement('div');
            streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
            streamBubble.style.position = 'relative';
            const agentColor = agentColors[selectedAgent];
            if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
            _insert(streamBubble);
            _streamLastParse = 0;
        }
        streamPending += content;
        if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
        return;
    }

    // 'text' event signals streaming finished — flush typewriter buffer,
    // replace with authoritative DB content, finalize with copy/timestamp.
    if (type === 'text' && streamBubble) {
        _streamFlush();
        streamBubble.classList.remove('streaming');
        const finalText = content || streamContent;
        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(finalText));
        addCopyBtn(streamBubble, finalText);
        addTimestamp(streamBubble, ts);
        streamBubble = null;
        streamContent = '';
        streamPending = '';
        return;
    }

    if (type === 'status') {
        const rl = _parseRateLimitStatus(content);
        const badge = document.createElement('div');
        if (rl) {
            // Rate limit: trigger the global banner (live logs only, not history replay)
            if (!anchor) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
            badge.className = 'text-center text-xs py-1 text-amber-400 italic';
            badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
        } else {
            badge.className = 'text-center text-xs py-1 text-slate-500 italic';
            badge.textContent = `⚡ ${content}`;
        }
        addTimestamp(badge, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(badge);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (type === 'subagent_start' || type === 'subagent_end' || type === 'subagent_progress') {
        const parts = content.split('|').map(p => p.trim());
        const meta = {};
        const textParts = [];
        for (const p of parts) {
            const eq = p.indexOf('=');
            if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
            else if (p) textParts.push(p);
        }
        const desc = textParts[0] || textParts[1] || '';
        const el = document.createElement('div');
        el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';

        const subId = (payload && payload.subagent_id) || meta.id || '';

        if (type === 'subagent_start') {
            // Collapsible accordion: header + body where live sub-agent logs nest.
            el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
            if (subId) el.dataset.subagentId = subId;
            const header = document.createElement('div');
            header.style.cssText = 'cursor:pointer;user-select:none';
            header.innerHTML = `<span class="sa-caret">▶</span> 🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
            const body = document.createElement('div');
            body.className = 'sa-body';
            body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
            let _expanded = false;
            header.addEventListener('click', () => {
                _expanded = !_expanded;
                body.style.display = _expanded ? 'block' : 'none';
                header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
            });
            el.appendChild(header);
            el.appendChild(body);
        } else if (type === 'subagent_progress') {
            // Update the live progress line inside the matching accordion (or standalone)
            const tokens = meta.tokens ? (parseInt(meta.tokens) >= 1000 ? (parseInt(meta.tokens) / 1000).toFixed(1) + 'k' : meta.tokens) : '';
            const line = `⏳ ${meta.tool ? 'using ' + meta.tool : 'working'}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
            if (host) {
                let prog = host.querySelector('.sa-progress');
                if (!prog) {
                    prog = document.createElement('div');
                    prog.className = 'sa-progress';
                    prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                    host.appendChild(prog);
                }
                prog.textContent = line;
                return;  // updated in place, no new bubble
            }
            el.style.cssText += ';color:#64748b';
            el.textContent = `⏳ "${desc}" — ${line}`;
        } else {  // subagent_end → mark the accordion done + collapse
            const ok = !meta.status || meta.status === 'completed';
            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
            const summaryText = textParts.slice(1).join(' | ').trim();
            if (host) {
                const hdr = host.querySelector('div');
                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
                const prog = host.querySelector('.sa-progress');
                if (prog) prog.remove();
                if (summaryText) {
                    const sumEl = document.createElement('div');
                    sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                    sumEl.textContent = summaryText;
                    host.appendChild(sumEl);
                }
                host.style.borderLeftColor = ok ? '#22c55e' : '#ef4444';
                return;  // updated existing accordion, no new bubble
            }
            el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
            if (summaryText) {
                const sumEl = document.createElement('div');
                sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
                sumEl.textContent = summaryText.length > 300 ? summaryText.slice(0, 300) + '…' : summaryText;
                el.appendChild(sumEl);
            }
        }
        addTimestamp(el, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(el);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    const div = document.createElement('div');
    div.className = `px-3 py-2 rounded-lg text-sm break-words ${
        type === 'user_message' ? 'chat-user ml-16' :
        type === 'tool' ? 'chat-tool' :
        type === 'tool_result' ? 'chat-tool-result' :
        type === 'error' ? 'text-red-400 text-xs' :
        'chat-bot markdown-body'
    }`;
    if (type === 'user_message') {
        content = content.replace(/^\[\d{2}:\d{2}\] /, '');
        // Hide prompt injection (system prompt prepended to first message after resume)
        if (content.startsWith('[Orchestra platform note:') || content.startsWith('[Orchestra platform')) return;
        // [from:agent-name] prefix means this was an agent-to-agent message injected by the MCP send_message tool,
        // not a human message — style it differently (colored border, sender label)
        const fromMatch = content.match(/^\[from:(.+?)\]\s*([\s\S]*)$/);
        if (fromMatch) {
            const sender = fromMatch[1];
            const msg = fromMatch[2];
            const senderColor = agentColors[sender] || Object.entries(agentColors).find(([k]) => k.startsWith(sender))?.[1] || '#64748b';
            div.style.borderLeft = `3px solid ${senderColor}`;
            div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
            const label = document.createElement('div');
            label.className = 'text-xs mb-1';
            label.style.color = senderColor;
            label.textContent = `${sender} → ${selectedAgent}`;
            div.appendChild(label);
            const body = document.createElement('div');
            body.className = 'markdown-body';
            body.innerHTML = DOMPurify.sanitize(marked.parse(msg));
            div.appendChild(body);
        } else {
            div.className += ' markdown-body';
            div.innerHTML = DOMPurify.sanitize(marked.parse(content));
            renderImages(div, content);
        }
    }
    else if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30);
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        const icon = toolIcon(rawName);
        const short = toolShortName(rawName);
        const isOrch = rawName.startsWith('mcp__orchestra__');

        div.dataset.lastTool = '1';
        div.dataset.toolContent = content;
        div.dataset.toolRawName = rawName;
        div.style.cursor = 'pointer';

        const header = document.createElement('div');
        header.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
        header.style.color = isOrch ? '#a78bfa' : '#38bdf8';
        let toolDesc = '';
        try { toolDesc = JSON.parse(body).description || ''; } catch {}
        header.innerHTML = `${icon} ${DOMPurify.sanitize(short)}${toolDesc ? ` <span style="color:#64748b;font-weight:normal">— ${DOMPurify.sanitize(toolDesc)}</span>` : ''}`;
        div.appendChild(header);

        const isProgress = rawName === 'mcp__orchestra__update_progress' || rawName === 'update_progress';
        if (isProgress) {
            try {
                const d = JSON.parse(body);
                const pct = d.percent || 0;
                const status = d.status || '';
                div.className = 'px-3 py-1 rounded-lg text-xs';
                div.style.cssText = 'border-left:3px solid #818cf8;background:rgba(99,102,241,0.08)';
                div.innerHTML = '';
                div.dataset.lastTool = '1';
                div.dataset.toolContent = content;
                div.dataset.toolRawName = rawName;
                const bar = document.createElement('div');
                bar.style.cssText = 'display:flex;align-items:center;gap:8px';
                const track = document.createElement('div');
                track.style.cssText = 'flex:1;height:6px;background:rgba(51,65,85,0.5);border-radius:3px;overflow:hidden';
                const fill = document.createElement('div');
                fill.style.cssText = `width:${Math.min(pct,100)}%;height:100%;background:#818cf8;border-radius:3px;transition:width 0.3s`;
                track.appendChild(fill);
                const label = document.createElement('span');
                label.style.cssText = 'color:#e2e8f0;font-weight:600;white-space:nowrap';
                label.textContent = `${pct}%`;
                const desc = document.createElement('span');
                desc.style.cssText = 'color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px';
                desc.textContent = status;
                bar.append(track, label, desc);
                div.appendChild(bar);
                div.dataset.isEdit = '1';
            } catch {}
        }
        const isSendMsg = rawName === 'mcp__orchestra__send_message';
        if (isSendMsg) {
            try {
                const d = JSON.parse(body);
                const to = d.to || d.message?.substring(0, 30) || '?';
                const msg = d.message || '';
                header.textContent = `📨 → ${to}`;
                header.style.color = '#a78bfa';
                const SEND_PREVIEW_H = 90;
                const bodyEl = document.createElement('div');
                bodyEl.className = 'text-xs opacity-80 markdown-body';
                bodyEl.style.cssText = `max-height:${SEND_PREVIEW_H}px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word`;
                bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(msg));
                div.appendChild(bodyEl);
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.cssText = 'color:#a78bfa;cursor:pointer';
                hint.textContent = '▼ expand';
                div.appendChild(hint);
                div.style.cursor = 'pointer';
                let sendExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    sendExpanded = !sendExpanded;
                    bodyEl.style.maxHeight = sendExpanded ? 'none' : SEND_PREVIEW_H + 'px';
                    bodyEl.style.overflowY = sendExpanded ? 'visible' : 'hidden';
                    hint.textContent = sendExpanded ? '▲ collapse' : '▼ expand';
                });
                requestAnimationFrame(() => {
                    if (bodyEl.scrollHeight <= SEND_PREVIEW_H + 4) { hint.style.display = 'none'; bodyEl.style.maxHeight = 'none'; bodyEl.style.overflowY = 'visible'; }
                });
                div.dataset.isEdit = '1';
            } catch {}
        }
        const isSpawnWorker = rawName === 'mcp__orchestra__spawn_worker';
        if (isSpawnWorker) {
            try {
                const d = JSON.parse(body);
                const workerName = d.name || '?';
                const task = d.task || '';
                const model = d.model || 'claude-sonnet-4-6';
                const sysPrompt = d.system_prompt || '';
                const repoPath = d.repo_path || '';

                header.textContent = `🚀 Spawning ${workerName}`;
                header.style.color = '#a78bfa';

                const MODEL_SHORT = {
                    'claude-opus-4-8[1m]': 'Opus 4.8 1M',
                    'claude-opus-4-6[1m]': 'Opus 4.6 1M',
                    'claude-opus-4-6': 'Opus 4.6',
                    'claude-sonnet-4-6': 'Sonnet 4.6',
                    'claude-haiku-4-5': 'Haiku 4.5',
                };
                const MODEL_COLOR = {
                    'claude-opus-4-8[1m]': '#c084fc',
                    'claude-opus-4-6[1m]': '#a78bfa',
                    'claude-opus-4-6': '#a78bfa',
                    'claude-sonnet-4-6': '#38bdf8',
                    'claude-haiku-4-5': '#4ade80',
                };
                if (model) {
                    const badge = document.createElement('span');
                    badge.textContent = MODEL_SHORT[model] || model;
                    badge.style.cssText = `font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:${MODEL_COLOR[model] || '#94a3b8'};border-color:${MODEL_COLOR[model] || '#94a3b8'};opacity:0.8;vertical-align:middle;margin-left:6px`;
                    header.appendChild(badge);
                }
                const role = d.role || '';
                if (role && role !== 'worker') {
                    const roleBadge = document.createElement('span');
                    roleBadge.textContent = role;
                    roleBadge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:#fbbf24;border-color:#fbbf24;opacity:0.8;vertical-align:middle;margin-left:4px';
                    header.appendChild(roleBadge);
                }

                const PREVIEW = 200;
                let cutAt = PREVIEW;
                if (task.length > PREVIEW) {
                    const nl = task.lastIndexOf('\n', PREVIEW);
                    if (nl > PREVIEW / 2) cutAt = nl;
                }
                const hasMoreTask = task.length > cutAt;
                const expandables = [];

                if (task) {
                    const taskEl = document.createElement('div');
                    taskEl.className = 'text-xs opacity-80 markdown-body';
                    taskEl.innerHTML = DOMPurify.sanitize(marked.parse(hasMoreTask ? task.slice(0, cutAt) : task));
                    div.appendChild(taskEl);
                    if (hasMoreTask) {
                        const restEl = document.createElement('div');
                        restEl.className = 'text-xs opacity-80 markdown-body';
                        restEl.innerHTML = DOMPurify.sanitize(marked.parse(task.slice(cutAt)));
                        restEl.style.display = 'none';
                        div.appendChild(restEl);
                        expandables.push(restEl);
                    }
                }

                if (sysPrompt) {
                    const promptLabel = document.createElement('div');
                    promptLabel.className = 'text-xs mt-2';
                    promptLabel.style.cssText = 'color:#64748b;font-weight:500';
                    promptLabel.textContent = '📋 System prompt';
                    promptLabel.style.display = 'none';
                    div.appendChild(promptLabel);
                    expandables.push(promptLabel);
                    const promptEl = document.createElement('div');
                    promptEl.style.cssText = 'margin-top:4px;padding:6px 8px;background:#0d1117;border:1px solid #1e293b;border-radius:6px;font-size:11px;white-space:pre-wrap;word-break:break-word;color:#94a3b8;max-height:200px;overflow-y:auto;display:none';
                    promptEl.textContent = sysPrompt;
                    div.appendChild(promptEl);
                    expandables.push(promptEl);
                }

                if (repoPath) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                    pathEl.textContent = repoPath;
                    pathEl.title = repoPath;
                    div.appendChild(pathEl);
                }

                if (expandables.length) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#a78bfa;cursor:pointer';
                    hint.textContent = `▼ expand`;
                    div.appendChild(hint);
                    div.style.cursor = 'pointer';
                    let spawnExpanded = false;
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        spawnExpanded = !spawnExpanded;
                        expandables.forEach(el => el.style.display = spawnExpanded ? 'block' : 'none');
                        hint.textContent = spawnExpanded ? '▲ collapse' : '▼ expand';
                    });
                }

                div.dataset.isEdit = '1';
            } catch {}
        }
        const isWebSearchCall = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
        if (isWebSearchCall) {
            try {
                const d = JSON.parse(body);
                const q = d.query || '';
                header.textContent = `🌐 Searching: "${q}"`;
                header.style.color = '#38bdf8';
                if (d.model) {
                    const badge = document.createElement('span');
                    badge.textContent = d.model;
                    badge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid #38bdf8;color:#38bdf8;opacity:0.8;vertical-align:middle;margin-left:6px';
                    header.appendChild(badge);
                }
            } catch {}
        }
        const isToolSearchCall = rawName === 'ToolSearch';
        if (isToolSearchCall) {
            try {
                const d = JSON.parse(body);
                const q = d.query || '';
                header.textContent = `🔍 Loading: ${q}`;
                header.style.color = '#38bdf8';
            } catch {}
        }
        const isBugReport = rawName === 'mcp__orchestra__report_bug';
        if (isBugReport) {
            try {
                const d = JSON.parse(body);
                header.textContent = `🐛 Bug: ${d.title || '?'}`;
                header.style.color = '#f97316';
                if (d.description) {
                    const descLines = d.description.split('\n');
                    const PREVIEW = 5;
                    const descEl = document.createElement('div');
                    descEl.className = 'text-xs markdown-body';
                    descEl.style.cssText = 'margin-top:4px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                    descEl.innerHTML = DOMPurify.sanitize(marked.parse(d.description));
                    div.appendChild(descEl);
                    if (descLines.length > PREVIEW) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#f97316;cursor:pointer';
                        hint.textContent = '▼ expand';
                        div.appendChild(hint);
                        let bugExpanded = false;
                        div.style.cursor = 'pointer';
                        div.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            bugExpanded = !bugExpanded;
                            descEl.style.maxHeight = bugExpanded ? 'none' : '90px';
                            descEl.style.overflowY = bugExpanded ? 'visible' : 'hidden';
                            hint.textContent = bugExpanded ? '▲ collapse' : '▼ expand';
                        });
                    }
                }
            } catch {}
        }
        const isWebFetch = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
        if (isWebFetch) {
            try {
                const d = JSON.parse(body);
                const url = d.url || '';
                let domain = '?';
                try { domain = new URL(url).hostname; } catch {}
                header.textContent = `🌐 Fetching: ${domain}`;
                header.style.color = '#38bdf8';
                if (url) {
                    const linkEl = document.createElement('a');
                    linkEl.href = url;
                    linkEl.target = '_blank';
                    linkEl.style.cssText = 'display:block;font-size:10px;color:#64748b;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none';
                    linkEl.textContent = url;
                    linkEl.onmouseenter = () => linkEl.style.color = '#94a3b8';
                    linkEl.onmouseleave = () => linkEl.style.color = '#64748b';
                    div.appendChild(linkEl);
                }
                if (d.prompt) {
                    const promptEl = document.createElement('div');
                    promptEl.className = 'text-xs';
                    promptEl.style.cssText = 'margin-top:4px;color:#94a3b8;max-height:90px;overflow:hidden;white-space:pre-wrap';
                    promptEl.textContent = d.prompt;
                    div.appendChild(promptEl);
                    if (d.prompt.split('\n').length > 5 || d.prompt.length > 300) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                        hint.textContent = '▼ expand';
                        div.appendChild(hint);
                        let fetchExpanded = false;
                        div.style.cursor = 'pointer';
                        div.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            fetchExpanded = !fetchExpanded;
                            promptEl.style.maxHeight = fetchExpanded ? 'none' : '90px';
                            promptEl.style.overflowY = fetchExpanded ? 'visible' : 'hidden';
                            hint.textContent = fetchExpanded ? '▲ collapse' : '▼ expand';
                        });
                    }
                }
            } catch {}
        }
        const isSendFile = rawName === 'mcp__orchestra__send_file';
        if (isSendFile) {
            try {
                const d = JSON.parse(body);
                const filePath = d.path || '';
                const fileName = filePath.split('/').pop() || '?';
                header.textContent = `📎 Sending: ${fileName}`;
                header.style.color = '#22c55e';
                if (filePath) div.dataset.filePath = filePath;
                if (d.caption) {
                    const capEl = document.createElement('div');
                    capEl.className = 'text-xs';
                    capEl.style.cssText = 'margin-top:2px;color:#cbd5e1';
                    capEl.textContent = d.caption;
                    div.appendChild(capEl);
                }
                if (filePath) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                    pathEl.textContent = filePath;
                    pathEl.title = filePath;
                    div.appendChild(pathEl);
                }
            } catch {}
        }
        const _orchSimple = {
            'mcp__orchestra__kill_worker': (d) => ({ icon: '💀', label: `Kill: ${d.name||'?'}`, color: '#ef4444' }),
            'mcp__orchestra__stop_worker': (d) => ({ icon: '⏸️', label: `Stop: ${d.name||'?'}`, color: '#eab308' }),
            'mcp__orchestra__compact_worker': (d) => ({ icon: '🗜', label: `Compact: ${d.name||'?'}`, color: '#eab308' }),
            'mcp__orchestra__rename_worker': (d) => ({ icon: '✏️', label: `Rename: ${d.old_name||'?'} → ${d.new_name||'?'}`, color: '#38bdf8' }),
            'mcp__orchestra__change_worker_model': (d) => ({ icon: '🔄', label: `Model: ${d.name||'?'} → ${d.model||'?'}`, color: '#38bdf8' }),
            'mcp__orchestra__update_worker_description': (d) => ({ icon: '✏️', label: `${d.name||'?'} — description updated`, color: '#38bdf8', sub: d.description ? `"${d.description}"` : '' }),
            'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
            'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
            'mcp__orchestra__list_jobs': () => ({ icon: '📊', label: 'Jobs', color: '#38bdf8' }),
            'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
            'mcp__orchestra__get_worker_info': (d) => ({ icon: '🤖', label: `Info: ${d.name||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price} ${CUR}` : '' }),
            'mcp__orchestra__task_update': (d) => { const f = Object.keys(d).filter(k=>k!=='par').map(k=>`${k}→${d[k]}`).join(', '); return { icon: '✏️', label: `#${taskNum(d.par)||'?'}: ${f}`, color: '#38bdf8' }; },
            'mcp__orchestra__task_list': (d) => { const f = [d.status,d.project,d.assignee].filter(Boolean).join(', '); return { icon: '📋', label: `Tasks${f ? ' ('+f+')' : ''}`, color: '#a78bfa' }; },
            'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `Task #${taskNum(d.par)||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'} ${CUR}`, color: '#22c55e', sub: d.note || '' }),
            'mcp__orchestra__payment_status': () => ({ icon: '💰', label: 'Balance', color: '#eab308' }),
            'mcp__orchestra__bg_create': (d) => { const i = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[d.type]||'⚙️'; return { icon: i, label: `BG ${d.type||'job'}${d.delay_seconds ? ' '+Math.round(d.delay_seconds/60)+'m' : ''}`, color: '#38bdf8', sub: d.message || d.target || '' }; },
            'mcp__orchestra__bg_list': () => ({ icon: '📊', label: 'BG Jobs', color: '#a78bfa' }),
            'mcp__orchestra__bg_cancel': (d) => ({ icon: '⏹', label: `Cancel ${(d.job_id||'').slice(0,8)}`, color: '#94a3b8' }),
        };
        const isOrchSimple = _orchSimple[rawName];
        if (isOrchSimple) {
            try {
                const d = JSON.parse(body);
                const cfg = isOrchSimple(d);
                header.textContent = `${cfg.icon} ${cfg.label}`;
                header.style.color = cfg.color;
                if (cfg.sub) {
                    const subEl = document.createElement('div');
                    subEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
                    subEl.textContent = cfg.sub;
                    div.appendChild(subEl);
                }
            } catch {}
        }
        const isGlob = rawName === 'Glob';
        if (isGlob) {
            try {
                const d = JSON.parse(body);
                header.textContent = `🔎 Glob: ${d.pattern || '?'}`;
                header.style.color = '#38bdf8';
                if (d.path) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px';
                    pathEl.textContent = d.path;
                    div.appendChild(pathEl);
                }
            } catch {}
        }
        const isSkill = rawName === 'Skill';
        if (isSkill) {
            try {
                const d = JSON.parse(body);
                header.textContent = `⚡ Skill: ${d.skill || '?'}`;
                header.style.color = '#eab308';
            } catch {}
        }
        const isYougile = rawName.startsWith('mcp__yougile__');
        if (isYougile) {
            try {
                const d = JSON.parse(body);
                const action = rawName.replace('mcp__yougile__', '').replace(/_/g, ' ');
                header.textContent = `📋 ${action}${d.title ? ': ' + d.title : ''}`;
                header.style.color = '#f97316';
                if (d.task_id) {
                    const idEl = document.createElement('div');
                    idEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px';
                    idEl.textContent = `ID: ${d.task_id}`;
                    div.appendChild(idEl);
                }
            } catch {}
        }
        const isBashTool = rawName === 'Bash';
        if (isBashTool) {
            try {
                let cmd = body;
                try { const d = JSON.parse(body); cmd = d.command || body; } catch {}
                cmd = cmd.replace(/^\/(?:usr\/)?bin\/(?:bash|zsh) -lc /, '').replace(/^["']|["']$/g, '');
                const cmdLines = cmd.split('\n');
                const PREVIEW_LINES = 3;
                const previewCmd = cmdLines.slice(0, PREVIEW_LINES).join('\n');
                const restCmd = cmdLines.slice(PREVIEW_LINES).join('\n');
                const hasMoreCmd = cmdLines.length > PREVIEW_LINES;
                const cmdWrap = document.createElement('div');
                cmdWrap.className = 'diff-view';
                cmdWrap.style.marginTop = '4px';
                const previewPre = document.createElement('pre');
                previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
                previewPre.textContent = previewCmd;
                cmdWrap.appendChild(previewPre);
                if (hasMoreCmd) {
                    const restPre = document.createElement('pre');
                    restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                    restPre.dataset.role = 'bash-rest';
                    restPre.textContent = restCmd;
                    cmdWrap.appendChild(restPre);
                    const hint = document.createElement('div');
                    hint.className = 'diff-file';
                    hint.dataset.role = 'bash-hint';
                    hint.dataset.count = cmdLines.length - PREVIEW_LINES;
                    hint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    hint.textContent = `▼ ${cmdLines.length - PREVIEW_LINES} more lines`;
                    cmdWrap.appendChild(hint);
                }
                div.appendChild(cmdWrap);
                div.dataset.isBash = '1';
                div.style.cursor = 'pointer';
                let bashExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    bashExpanded = !bashExpanded;
                    const restPre = cmdWrap.querySelector('[data-role="bash-rest"]');
                    const hint = cmdWrap.querySelector('[data-role="bash-hint"]');
                    if (restPre) restPre.style.display = bashExpanded ? 'block' : 'none';
                    if (hint) hint.textContent = bashExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                    const resWrap = div.querySelector('[data-role="bash-result"]');
                    const resHint = div.querySelector('[data-role="bash-result-hint"]');
                    if (resWrap) resWrap.style.display = bashExpanded ? 'block' : 'none';
                    if (resHint) resHint.textContent = bashExpanded ? '▲ collapse result' : `▼ ${resHint.dataset.count} more lines`;
                });
            } catch {}
        }
        const isAgentTool = rawName === 'Agent';
        if (isAgentTool) {
            try {
                const d = JSON.parse(body);
                const desc = d.description || '';
                const prompt = d.prompt || '';
                header.textContent = '🤖 Agent';
                header.style.color = '#a78bfa';
                if (desc) {
                    const descEl = document.createElement('div');
                    descEl.className = 'text-xs font-medium mb-1';
                    descEl.style.color = '#c7d2fe';
                    descEl.textContent = desc;
                    div.appendChild(descEl);
                }
                if (prompt) {
                    const promptLines = prompt.split('\n');
                    const PREVIEW_LINES = 2;
                    const previewPrompt = promptLines.slice(0, PREVIEW_LINES).join('\n');
                    const restPrompt = promptLines.slice(PREVIEW_LINES).join('\n');
                    const hasMorePrompt = promptLines.length > PREVIEW_LINES;
                    const promptWrap = document.createElement('div');
                    promptWrap.className = 'diff-view';
                    promptWrap.style.marginTop = '4px';
                    const previewPre = document.createElement('pre');
                    previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word';
                    previewPre.textContent = previewPrompt;
                    promptWrap.appendChild(previewPre);
                    if (hasMorePrompt) {
                        const restPre = document.createElement('pre');
                        restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word;display:none';
                        restPre.dataset.role = 'agent-rest';
                        restPre.textContent = restPrompt;
                        promptWrap.appendChild(restPre);
                        const hint = document.createElement('div');
                        hint.className = 'diff-file';
                        hint.dataset.role = 'agent-hint';
                        hint.dataset.count = promptLines.length - PREVIEW_LINES;
                        hint.style.cssText = 'cursor:pointer;text-align:center;color:#a78bfa;font-size:10px';
                        hint.textContent = `▼ ${promptLines.length - PREVIEW_LINES} more lines`;
                        promptWrap.appendChild(hint);
                    }
                    div.appendChild(promptWrap);
                    div.style.cursor = 'pointer';
                    let agentExpanded = false;
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        agentExpanded = !agentExpanded;
                        const restPre = promptWrap.querySelector('[data-role="agent-rest"]');
                        const hint = promptWrap.querySelector('[data-role="agent-hint"]');
                        if (restPre) restPre.style.display = agentExpanded ? 'block' : 'none';
                        if (hint) hint.textContent = agentExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                    });
                }
                div.dataset.isEdit = '1';
            } catch {}
        }
        const isGrepTool = rawName === 'Grep';
        if (isGrepTool) {
            try {
                const d = JSON.parse(body);
                const grepPath = d.path || d.glob || '';
                const shortGrepPath = grepPath.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || grepPath;
                header.textContent = `🔎 Grep: ${d.pattern || ''}${shortGrepPath ? ' in ' + shortGrepPath : ''}`;
                header.style.color = '#38bdf8';
                div.dataset.isGrep = '1';
                div.dataset.grepPattern = d.pattern || '';
                div.dataset.grepPath = grepPath;
            } catch {}
        }
        const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
        const isReadTool = rawName === 'Read';
        if (isReadTool) {
            try { const d = JSON.parse(body); if (d.file_path) div.dataset.filePath = d.file_path; } catch {}
        }
        const diffEl = isEditTool ? renderEditDiff(body) : null;
        const readEl = isReadTool ? renderReadView(body) : null;

        if (readEl) {
            div.appendChild(readEl);
            div.dataset.isRead = '1';
            div.style.cursor = 'pointer';
            div.addEventListener('click', () => {
                const restEl = readEl.querySelector('[data-role="read-rest"]');
                const moreEl = readEl.querySelector('[data-role="read-more"]');
                if (restEl && moreEl) {
                    const showing = restEl.style.display !== 'none';
                    restEl.style.display = showing ? 'none' : 'block';
                    moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
                }
            });
        } else if (diffEl) {
            div.appendChild(diffEl);
            div.dataset.isEdit = '1';
            div.style.cursor = 'pointer';
            div.addEventListener('click', () => {
                const restEl = diffEl.querySelector('[style*="display"]');
                const moreEl = diffEl.querySelector('.diff-file[style*="cursor"]');
                if (restEl && moreEl) {
                    const showing = restEl.style.display !== 'none';
                    restEl.style.display = showing ? 'none' : 'block';
                    const restCount = moreEl.dataset.count || '0';
                    moreEl.textContent = showing ? `▼ ${restCount} more lines` : `▲ collapse`;
                }
            });
        } else if (!isProgress && !isSendMsg && !isGrepTool && !isBashTool && !isAgentTool && !isSpawnWorker && !isWebSearchCall && !isToolSearchCall && !isBugReport && !isWebFetch && !isSendFile && !isOrchSimple && !isGlob && !isSkill && !isYougile) {
            let _inputJsonRendered = false;
            if (body) {
                try {
                    const _inputParsed = JSON.parse(body);
                    if (_inputParsed && typeof _inputParsed === 'object' && !Array.isArray(_inputParsed)) {
                        const gridWrap = document.createElement('div');
                        gridWrap.className = 'text-xs opacity-80 tool-body';
                        gridWrap.style.cssText = 'margin-top:2px';
                        _renderJsonGrid(_inputParsed, gridWrap);
                        div.appendChild(gridWrap);
                        _inputJsonRendered = true;
                    }
                } catch {}
            }
            if (!_inputJsonRendered && body) {
                const toolPreview = body.length > 200 ? body.slice(0, 200) + '…' : body;
                const toolFull = body.length > 200 ? body : null;
                const bodyEl = document.createElement('div');
                bodyEl.style.whiteSpace = 'pre-wrap';
                bodyEl.className = 'text-xs opacity-70 tool-body';
                bodyEl.textContent = toolPreview;
                bodyEl.dataset.preview = toolPreview;
                if (toolFull) bodyEl.dataset.full = toolFull;
                div.appendChild(bodyEl);
                if (toolFull) {
                    const remaining = body.split('\n').length - toolPreview.split('\n').length;
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.color = '#38bdf8';
                    hint.textContent = `▼ ${remaining} more lines`;
                    hint.dataset.role = 'expand-hint';
                    div.appendChild(hint);
                }
                let expanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    expanded = !expanded;
                    const tb = div.querySelector('.tool-body');
                    if (tb && tb.dataset.full) tb.textContent = expanded ? tb.dataset.full : tb.dataset.preview;
                    const hint = div.querySelector('[data-role="expand-hint"]');
                    if (hint) hint.style.display = expanded ? 'none' : 'block';
                    const rb = div.querySelector('.result-body');
                    if (rb && rb.dataset.full) rb.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? rb.dataset.full : rb.dataset.preview, {ADD_ATTR: ['target']});
                });
            }
        }
    }
    else if (type === 'tool_result') {
        const chat = $('#chat');
        const lastTool = _findLastBefore(chat, '[data-last-tool]', anchor);
        if (_isBase64Image) {
            const b64Match = content.match(/data['":\s]+['"]([A-Za-z0-9+/=\s]{100,})['"]/);
            if (lastTool) {
                delete lastTool.dataset.lastTool;
                const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                if (skeleton) skeleton.remove();
            }
            const target = lastTool || div;
            if (b64Match) {
                const img = document.createElement('img');
                // Use original file via API if Read tool has file_path — SDK compresses base64
                const origPath = lastTool && lastTool.dataset.filePath;
                const thumbSrc = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
                img.src = origPath ? `/api/files/raw?path=${encodeURIComponent(origPath)}` : thumbSrc;
                img.onerror = () => { img.src = thumbSrc; };
                img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
                img.addEventListener('click', () => _showImageOverlay(origPath ? img.src : thumbSrc));
                target.appendChild(img);
            } else {
                const placeholder = document.createElement('div');
                placeholder.className = 'text-xs';
                placeholder.style.cssText = 'color:#64748b;margin-top:4px';
                placeholder.textContent = '🖼 [Image result]';
                target.appendChild(placeholder);
            }
            addTimestamp(target, ts);
            if (!lastTool) {
                const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            }
            return;
        }
        const toolErrorMatch = content.match(/<tool_use_error>([\s\S]*?)<\/tool_use_error>/);
        if (toolErrorMatch) {
            const errMsg = toolErrorMatch[1].trim();
            const errDiv = document.createElement('div');
            errDiv.className = 'px-3 py-2 rounded-lg text-xs text-red-400 bg-red-950/30 border border-red-900/50';
            errDiv.textContent = '⚠️ ' + errMsg;
            if (lastTool) {
                delete lastTool.dataset.lastTool;
                const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                if (skeleton) skeleton.remove();
                lastTool.appendChild(errDiv);
                addTimestamp(lastTool, ts);
            } else {
                div.appendChild(errDiv);
                addTimestamp(div, ts);
                const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            }
            return;
        }
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        // Strip raw JSON link arrays from WebSearch results (shown as ugly JSON at top)
        const stripped = clean.replace(/^(Links:\s*\[.*?\}\]\s*\n?)+/gms, '');
        const escaped = stripped.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        // Render markdown links [text](url) first, then bare URLs
        const mdLinked = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const linked = mdLinked.replace(/((?<!href="|">)https?:\/\/[^\s\])"&<]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const _resultLines = linked.split('\n');
        const _RESULT_PREVIEW = 5;
        const _hasMore = _resultLines.length > _RESULT_PREVIEW;
        const preview = _hasMore ? _resultLines.slice(0, _RESULT_PREVIEW).join('\n') : linked;
        const full = _hasMore ? linked : null;

        if (lastTool) {
            delete lastTool.dataset.lastTool;
            if (lastTool.dataset.isEdit) {
                addTimestamp(lastTool, ts);
                return;
            }
            const isToolSearch = lastTool.dataset.toolRawName === 'ToolSearch';
            if (isToolSearch) {
                let toolName = '';
                try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
                if (!toolName) { const m = content.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr && toolName) hdr.textContent = `✅ Loaded: ${toolName}`;
                else if (hdr) hdr.textContent = '✅ Tool loaded';
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__report_bug') {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) { hdr.textContent = '✅ Bug reported'; hdr.style.color = '#22c55e'; }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_file') {
                const hdr = lastTool.querySelector('.flex.items-center');
                const hasError = content.includes('error') || content.includes('Error') || content.includes('failed');
                if (hdr) {
                    hdr.textContent = hasError ? '❌ Send failed' : '✅ Sent to TG';
                    hdr.style.color = hasError ? '#ef4444' : '#22c55e';
                }
                const fp = lastTool.dataset.filePath;
                if (!hasError && fp) {
                    const openBtn = document.createElement('button');
                    openBtn.textContent = '📂 Открыть';
                    openBtn.style.cssText = 'margin-top:4px;padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
                    openBtn.onmouseenter = () => { openBtn.style.borderColor = 'rgba(99,102,241,0.6)'; openBtn.style.color = '#c7d2fe'; };
                    openBtn.onmouseleave = () => { openBtn.style.borderColor = 'rgba(99,102,241,0.3)'; openBtn.style.color = '#a5b4fc'; };
                    openBtn.onclick = () => {
                        fetch(`/api/open-file?path=${encodeURIComponent(fp)}`)
                            .then(r => { if (r.status === 403) throw new Error('disabled'); if (!r.ok) throw new Error('fail'); return r.json(); })
                            .then(() => { openBtn.textContent = '✅ Opened'; setTimeout(() => { openBtn.textContent = '📂 Открыть'; }, 1500); })
                            .catch(e => { openBtn.textContent = e.message === 'disabled' ? '🚫 Disabled on server' : '❌ Not found'; setTimeout(() => { openBtn.textContent = '📂 Открыть'; }, 2000); });
                    };
                    lastTool.appendChild(openBtn);
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const _tmTools = ['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__task_list','mcp__orchestra__task_get','mcp__orchestra__payment_receive','mcp__orchestra__payment_status','mcp__orchestra__bg_list','mcp__orchestra__get_worker_info'];
            if (_tmTools.includes(lastTool.dataset.toolRawName)) {
                const hdr = lastTool.querySelector('.flex.items-center');
                let parsed = null;
                try { parsed = JSON.parse(content); } catch {}
                const tn = lastTool.dataset.toolRawName;
                if (!parsed || parsed.error) {
                    if (hdr) { hdr.textContent = `❌ ${parsed?.error || clean.slice(0, 80)}`; hdr.style.color = '#ef4444'; }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (tn === 'mcp__orchestra__task_create' || tn === 'mcp__orchestra__task_get') {
                    const _k = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                    if (hdr) { hdr.textContent = `📋 #${parsed.par}: ${parsed.title || '?'}`; hdr.style.color = tn.includes('create') ? '#22c55e' : '#a78bfa'; }
                    const info = document.createElement('div');
                    info.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:10px;color:#64748b';
                    const stColor = {'done':'#22c55e','paid':'#22c55e','in_progress':'#38bdf8','new':'#e2e8f0','cancelled':'#ef4444'}[parsed.status] || '#e2e8f0';
                    if (parsed.status) info.innerHTML += `<div>Status: <b style="color:${stColor}">${parsed.status}</b></div>`;
                    if (parsed.project) info.innerHTML += `<div>Project: <span style="color:#94a3b8">${DOMPurify.sanitize(parsed.project)}</span></div>`;
                    const priceRub = parsed.price_rub ?? 0;
                    info.innerHTML += `<div>Price: <b style="color:#eab308">${_k(priceRub)} ${CUR}</b></div>`;
                    if (priceRub > 0) info.innerHTML += `<div>Paid: ${_k(parsed.paid_rub||0)}/${_k(priceRub)}${parsed.debt_rub > 0 ? ` <span style="color:#ef4444">debt ${_k(parsed.debt_rub)}</span>` : ''}</div>`;
                    if (parsed.assignee) info.innerHTML += `<div>Assignee: ${DOMPurify.sanitize(parsed.assignee)}</div>`;
                    if (parsed.created_at) info.innerHTML += `<div>Created: ${(parsed.created_at||'').slice(0,10)}</div>`;
                    if (parsed.updated_at) info.innerHTML += `<div>Updated: ${(parsed.updated_at||'').slice(0,10)}</div>`;
                    if (parsed.completed_at) info.innerHTML += `<div>Done: ${(parsed.completed_at||'').slice(0,10)}</div>`;
                    if (parsed.paid_at) info.innerHTML += `<div>Paid: ${(parsed.paid_at||'').slice(0,10)}</div>`;
                    lastTool.appendChild(info);
                    if (parsed.description) {
                        const descEl = document.createElement('div');
                        descEl.className = 'text-xs markdown-body';
                        descEl.style.cssText = 'margin-top:4px;max-height:54px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;line-height:1.4;color:#94a3b8';
                        descEl.innerHTML = DOMPurify.sanitize(marked.parse(parsed.description));
                        lastTool.appendChild(descEl);
                        lastTool.style.cursor = 'pointer';
                        let _tgExp = false;
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _tgExp = !_tgExp;
                            descEl.style.maxHeight = _tgExp ? 'none' : '54px';
                            descEl.style.overflowY = _tgExp ? 'visible' : 'hidden';
                        });
                    }
                    const sys = [];
                    if (parsed.yougile_id || parsed.yougile_task_id) sys.push(`yougile: ${parsed.yougile_id || parsed.yougile_task_id}`);
                    if (parsed.sync_revision) sys.push(`rev: ${parsed.sync_revision}`);
                    if (sys.length > 0) {
                        const sEl = document.createElement('div');
                        sEl.style.cssText = 'margin-top:4px;font-size:9px;color:#475569;font-family:monospace';
                        sEl.textContent = sys.join(' · ');
                        lastTool.appendChild(sEl);
                    }
                } else if (tn === 'mcp__orchestra__task_update') {
                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                    const changes = [];
                    if (parsed.old_status && parsed.new_status && parsed.old_status !== parsed.new_status) changes.push(`status ${parsed.old_status}→${parsed.new_status}`);
                    if (parsed.updated) {
                        for (const f of parsed.updated) {
                            if (f === 'status') continue;
                            if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ${CUR}`);
                            else if (f === 'assignee' && parsed.assignee != null) changes.push(`assignee→${parsed.assignee || '—'}`);
                            else if (f === 'title') changes.push('title');
                            else if (f === 'description') changes.push('description');
                            else changes.push(f);
                        }
                    }
                    const parNum = (parsed.par || '?').replace(/^[A-Z]+-/, '');
                    const titleStr = parsed.title ? ` "${parsed.title.slice(0,40)}"` : '';
                    if (hdr) { hdr.textContent = `✏️ #${parNum}${titleStr}: ${changes.length ? changes.join(', ') : 'updated'}`; hdr.style.color = '#22c55e'; }
                    if (parsed.old_title && parsed.title && parsed.old_title !== parsed.title) {
                        const titleDiff = document.createElement('div');
                        titleDiff.style.cssText = 'margin-top:3px;font-size:10px';
                        titleDiff.innerHTML = `<span style="color:#64748b;text-decoration:line-through">${DOMPurify.sanitize(parsed.old_title.slice(0,60))}</span> → <span style="color:#e2e8f0">${DOMPurify.sanitize(parsed.title.slice(0,60))}</span>`;
                        lastTool.appendChild(titleDiff);
                    }
                    if (parsed.description && (parsed.updated || []).includes('description')) {
                        const descWrap = document.createElement('div');
                        descWrap.style.cssText = 'margin-top:4px';
                        if (parsed.old_description) {
                            const oldEl = document.createElement('div');
                            oldEl.style.cssText = 'font-size:10px;color:#64748b;text-decoration:line-through;max-height:40px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                            oldEl.textContent = parsed.old_description.split('\n').slice(0,3).join('\n');
                            descWrap.appendChild(oldEl);
                        }
                        const newEl = document.createElement('div');
                        newEl.style.cssText = 'font-size:10px;color:#86efac;max-height:40px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere;margin-top:2px';
                        newEl.textContent = parsed.description.split('\n').slice(0,3).join('\n') + (parsed.description.split('\n').length > 3 ? '…' : '');
                        descWrap.appendChild(newEl);
                        lastTool.appendChild(descWrap);
                        if (parsed.description.split('\n').length > 3) {
                            lastTool.style.cursor = 'pointer';
                            let _duExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _duExp = !_duExp;
                                newEl.textContent = _duExp ? parsed.description : parsed.description.split('\n').slice(0,3).join('\n') + '…';
                                newEl.style.maxHeight = _duExp ? 'none' : '40px';
                                newEl.style.overflowY = _duExp ? 'visible' : 'hidden';
                            });
                        }
                    }
                    const detail = document.createElement('div');
                    detail.style.cssText = 'margin-top:3px;font-size:10px;color:#64748b;display:flex;gap:8px;flex-wrap:wrap';
                    if (parsed.price_rub > 0) detail.innerHTML += `<span>Price: <b style="color:#eab308">${_kr(parsed.price_rub)} ${CUR}</b></span>`;
                    if (parsed.paid_rub > 0) detail.innerHTML += `<span>Paid: ${_kr(parsed.paid_rub)}</span>`;
                    if (parsed.debt_rub > 0) detail.innerHTML += `<span style="color:#ef4444">Debt: ${_kr(parsed.debt_rub)}</span>`;
                    if (detail.innerHTML) lastTool.appendChild(detail);
                } else if (tn === 'mcp__orchestra__task_list') {
                    const tasks = parsed.tasks || [];
                    const _k = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
                    if (hdr) hdr.textContent = `📋 ${tasks.length} tasks` + (parsed.total_debt && parsed.total_debt !== '0' ? ` | debt: ${parsed.total_debt}` : '');
                    if (tasks.length > 0 && parsed.detailed) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px';
                        const PREVIEW = 3;
                        for (const [i, t] of tasks.entries()) {
                            const card = document.createElement('div');
                            card.style.cssText = `padding:6px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${t.status==='done'||t.status==='paid'?'#22c55e':t.status==='in_progress'?'#38bdf8':'#334155'}${i >= PREVIEW ? ';display:none' : ''}`;
                            card.dataset.taskRow = '1';
                            let h = `<div style="font-size:11px;color:#e2e8f0;font-weight:600">${DOMPurify.sanitize(t.par)}: ${DOMPurify.sanitize(t.title)}</div>`;
                            h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px 8px;font-size:10px;color:#64748b;margin-top:3px">';
                            h += `<div>Status: <b style="color:#e2e8f0">${t.status}</b></div>`;
                            if (t.price_rub > 0) h += `<div>Price: <b style="color:#eab308">${_k(t.price_rub)} ${CUR}</b>${t.debt_rub > 0 ? ` <span style="color:#ef4444">debt ${_k(t.debt_rub)}</span>` : ''}</div>`;
                            if (t.project) h += `<div>Project: ${DOMPurify.sanitize(t.project)}</div>`;
                            if (t.assignee) h += `<div>→ ${DOMPurify.sanitize(t.assignee)}</div>`;
                            if (t.created_at) h += `<div>Created: ${t.created_at.slice(0,10)}</div>`;
                            if (t.completed_at) h += `<div>Done: ${t.completed_at.slice(0,10)}</div>`;
                            h += '</div>';
                            if (t.description) {
                                const short = t.description.split('\n').slice(0,3).join('\n');
                                h += `<div style="font-size:10px;color:#94a3b8;margin-top:3px;max-height:40px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere">${DOMPurify.sanitize(short)}${t.description.length > short.length ? '…' : ''}</div>`;
                            }
                            card.innerHTML = h;
                            container.appendChild(card);
                        }
                        lastTool.appendChild(container);
                        if (tasks.length > PREVIEW) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${tasks.length - PREVIEW} more`;
                            lastTool.appendChild(hint);
                            let _tlExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _tlExp = !_tlExp;
                                container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'block' : 'none'; });
                                hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                            });
                        }
                    } else if (tasks.length > 0) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                        const PREVIEW = 4;
                        for (const [i, t] of tasks.entries()) {
                            const row = document.createElement('div');
                            row.style.cssText = `font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:6px;align-items:center${i >= PREVIEW ? ';display:none' : ''}`;
                            row.dataset.taskRow = '1';
                            const priceStr = t.price && t.price !== '0' ? `<span style="color:#eab308">${t.price}</span>` : '';
                            row.innerHTML = `<span style="color:#64748b;font-family:monospace;min-width:32px">#${t.par}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(t.title)}</span><span style="color:#64748b">${t.status}</span>${priceStr}`;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (tasks.length > PREVIEW) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${tasks.length - PREVIEW} more`;
                            lastTool.appendChild(hint);
                            let _tlExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _tlExp = !_tlExp;
                                container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'flex' : 'none'; });
                                hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                            });
                        }
                    }
                } else if (tn === 'mcp__orchestra__payment_receive') {
                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                    const amt = parsed.amount_rub ? _kr(parsed.amount_rub) : (parsed.amount || '?') + 'k';
                    if (hdr) { hdr.textContent = `💰 +${amt} ${CUR} received`; hdr.style.color = '#22c55e'; }
                    const payInfo = document.createElement('div');
                    payInfo.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                    let payHtml = '';
                    if (parsed.distributions && parsed.distributions.length > 0) {
                        payHtml += parsed.distributions.map(d => {
                            const a = d.allocated ? _kr(d.allocated) : (d.amount || '?') + 'k';
                            return `<div style="display:flex;gap:6px"><span style="color:#94a3b8;min-width:60px">${d.par}</span><span style="color:#22c55e">+${a} ${CUR}</span>${d.remaining != null ? `<span style="color:#475569">remaining: ${_kr(d.remaining)}</span>` : ''}</div>`;
                        }).join('');
                    }
                    if (parsed.balance_rub != null) payHtml += `<div style="margin-top:2px;color:#eab308">Balance: ${_kr(parsed.balance_rub)} ${CUR}</div>`;
                    if (payHtml) { payInfo.innerHTML = payHtml; lastTool.appendChild(payInfo); }
                } else if (tn === 'mcp__orchestra__payment_status') {
                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                    const bal = parsed.balance_rub != null ? _kr(parsed.balance_rub) : (parsed.balance_display || '0');
                    const debt = parsed.total_debt_rub != null ? _kr(parsed.total_debt_rub) : (parsed.total_debt_display || '0');
                    if (hdr) {
                        hdr.textContent = `💰 Balance: ${bal} ${CUR} | Debt: ${debt} ${CUR}`;
                        hdr.style.color = '#eab308';
                    }
                    const payments = parsed.recent_payments || parsed.payments || [];
                    if (payments.length > 0) {
                        const pEl = document.createElement('div');
                        pEl.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                        pEl.innerHTML = payments.slice(0, 5).map(p => {
                            const a = p.amount_rub ? _kr(p.amount_rub) : p.amount;
                            return `<div>${p.date}: <span style="color:#22c55e">+${a}</span>${p.note ? ' — '+DOMPurify.sanitize(p.note) : ''}</div>`;
                        }).join('');
                        lastTool.appendChild(pEl);
                    }
                    if (parsed.tasks_with_debt && parsed.tasks_with_debt.length > 0) {
                        const dEl = document.createElement('div');
                        dEl.style.cssText = 'margin-top:4px;font-size:10px;color:#ef4444';
                        dEl.innerHTML = '<div style="color:#64748b;margin-bottom:2px">Debt:</div>' + parsed.tasks_with_debt.map(t => `<div>${t.par}: ${_kr(t.debt_rub || t.debt)} ${CUR}</div>`).join('');
                        lastTool.appendChild(dEl);
                    }
                } else if (tn === 'mcp__orchestra__bg_list') {
                    const jobs = Array.isArray(parsed) ? parsed : (parsed.jobs || []);
                    if (hdr) hdr.textContent = `📊 ${jobs.length} jobs`;
                    if (jobs.length > 0) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                        for (const j of jobs.slice(0, 8)) {
                            const icon = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[j.type] || '⚙️';
                            const st = {'active':'🟢','triggered':'✅','expired':'⏰','cancelled':'❌','failed':'❌'}[j.status] || '⚪';
                            const row = document.createElement('div');
                            row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:4px;align-items:center';
                            row.innerHTML = `<span>${icon}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(j.target_name || '')} ${DOMPurify.sanitize((j.message||'').slice(0,30))}</span><span>${st}</span>`;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                    }
                } else if (tn === 'mcp__orchestra__get_worker_info') {
                    const stColor = {'running':'#22c55e','idle':'#eab308','error':'#ef4444','stopped':'#6b7280','starting':'#f97316'}[parsed.status] || '#94a3b8';
                    const MODEL_SHORT = {'claude-opus-4-8[1m]':'Opus 4.8 1M','claude-opus-4-6[1m]':'Opus 4.6 1M','claude-opus-4-6':'Opus 4.6','claude-sonnet-4-6':'Sonnet 4.6','claude-haiku-4-5':'Haiku 4.5','gpt-5.5':'GPT 5.5'};
                    const modelShort = MODEL_SHORT[parsed.model] || parsed.model || '?';
                    if (hdr) {
                        hdr.innerHTML = `🤖 <b>${DOMPurify.sanitize(parsed.name || '?')}</b> <span style="font-size:10px;color:#64748b">(${DOMPurify.sanitize(modelShort)})</span> — <span style="color:${stColor}">${parsed.status || '?'}</span>`;
                    }
                    const grid = document.createElement('div');
                    grid.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px';
                    const _row = (label, val, color) => { if (val != null && val !== '') grid.innerHTML += `<span style="color:#64748b">${label}</span><span style="color:${color||'#cbd5e1'}">${DOMPurify.sanitize(String(val))}</span>`; };
                    _row('Role', parsed.is_orchestrator ? '🎯 orchestrator' : '⚙️ worker');
                    _row('Branch', parsed.branch, '#818cf8');
                    const ctxPct = parsed.context_pct || 0;
                    const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                    _row('Context', `${ctxPct}%`, ctxColor);
                    _row('Cost', `$${parsed.cost_usd ?? 0}`, '#22c55e');
                    if (parsed.task_id) _row('Task', `#${parsed.task_id}`, '#a78bfa');
                    if (parsed.total_turns) _row('Turns', parsed.total_turns);
                    if (parsed.total_tool_calls) _row('Tool calls', parsed.total_tool_calls);
                    if (parsed.total_input_tokens || parsed.total_output_tokens) _row('Tokens', `${(parsed.total_input_tokens||0).toLocaleString()} in / ${(parsed.total_output_tokens||0).toLocaleString()} out`);
                    if (parsed.progress_pct > 0) _row('Progress', `${parsed.progress_pct}%${parsed.progress_status ? ' — '+parsed.progress_status : ''}`, '#38bdf8');
                    lastTool.appendChild(grid);
                    if (parsed.description) {
                        const descEl = document.createElement('div');
                        descEl.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8;font-style:italic;max-height:40px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere';
                        descEl.textContent = parsed.description;
                        lastTool.appendChild(descEl);
                        if (parsed.description.length > 120) {
                            lastTool.style.cursor = 'pointer';
                            let _wiExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _wiExp = !_wiExp;
                                descEl.style.maxHeight = _wiExp ? 'none' : '40px';
                                descEl.style.overflowY = _wiExp ? 'visible' : 'hidden';
                            });
                        }
                    }
                }
                addTimestamp(lastTool, ts);
                if (['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__payment_receive'].includes(tn)) loadTasks();
                return;
            }
            const _orchSimpleResults = {
                'mcp__orchestra__kill_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped/); return m ? { text: `💀 ${m[1]} killed`, color: '#22c55e' } : null; },
                'mcp__orchestra__stop_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped|stopped.*'(.+?)'/i); const n = m?.[1]||m?.[2]; return n ? { text: `⏸️ ${n} stopped`, color: '#22c55e' } : null; },
                'mcp__orchestra__rename_worker': (c) => { const m = c.match(/Worker '(.+?)' renamed to '(.+?)'/); return m ? { text: `✏️ ${m[1]} → ${m[2]}`, color: '#22c55e' } : null; },
                'mcp__orchestra__change_worker_model': (c) => { const m = c.match(/model.*changed|'(.+?)'/i); return { text: '✅ Model changed', color: '#22c55e' }; },
                'mcp__orchestra__update_worker_description': (c) => { const m = c.match(/Description updated for '(.+?)'/); return m ? { text: `✏️ ${m[1]} — description updated`, color: '#22c55e' } : { text: '✅ description updated', color: '#22c55e' }; },
                'mcp__orchestra__merge_worker': (c) => { const m = c.match(/(\d+) commits? merged|Merged/i); return m ? { text: `🔀 Merged${m[1] ? ' ('+m[1]+' commits)' : ''}`, color: '#22c55e' } : null; },
                'mcp__orchestra__send_message': (c) => { const m = c.match(/sent to '(.+?)'/i); return m ? { text: `✅ → ${m[1]}`, color: '#22c55e' } : c.includes('fail') || c.includes('error') || c.includes('Error') ? { text: `❌ ${c.substring(0, 60)}`, color: '#ef4444' } : { text: '✅ Sent', color: '#22c55e' }; },
                'mcp__orchestra__compact_worker': null,
                'mcp__orchestra__list_agents': null,
                'mcp__orchestra__list_orchestrators': null,
                'mcp__orchestra__list_jobs': null,
                'mcp__orchestra__get_worker_logs': null,
                'mcp__orchestra__bg_create': (c) => { const m = c.match(/Background job created: (\S+)/); return m ? { text: `✅ Job ${m[1].slice(0,12)}`, color: '#22c55e' } : c.includes('rror') ? null : { text: '✅ Job created', color: '#22c55e' }; },
                'mcp__orchestra__bg_cancel': (c) => { const m = c.match(/Job (\S+) cancelled/); return m ? { text: `⏹ ${m[1].slice(0,12)} cancelled`, color: '#94a3b8' } : c.includes('rror') ? null : { text: '⏹ Cancelled', color: '#94a3b8' }; },
                'mcp__orchestra__update_progress': () => ({ text: '✓', color: '#818cf8' }),
            };
            const _orchResultCfg = _orchSimpleResults[lastTool.dataset.toolRawName];
            if (_orchResultCfg !== undefined) {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (typeof _orchResultCfg === 'function') {
                    const hasErr = content.includes('failed') || content.includes('Failed') || content.includes('error') || content.includes('Error');
                    if (hasErr) {
                        const toolAction = lastTool.dataset.toolRawName.split('__').pop().replace(/_/g, ' ');
                        if (hdr) { hdr.textContent = `❌ ${toolAction} failed`; hdr.style.color = '#ef4444'; }
                        const errEl = document.createElement('div');
                        errEl.style.cssText = 'margin-top:4px;font-size:10px;color:#fca5a5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:54px;overflow-y:hidden;overflow-x:hidden';
                        errEl.textContent = clean;
                        lastTool.appendChild(errEl);
                        if (clean.split('\n').length > 3 || clean.length > 200) {
                            lastTool.style.cursor = 'pointer';
                            let _errExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _errExp = !_errExp;
                                errEl.style.maxHeight = _errExp ? 'none' : '54px';
                                errEl.style.overflowY = _errExp ? 'visible' : 'hidden';
                            });
                        }
                    } else {
                        const result = _orchResultCfg(clean);
                        if (hdr) { hdr.textContent = result?.text || '✅ Done'; hdr.style.color = result?.color || '#22c55e'; }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__compact_worker') {
                    let workerName = '';
                    try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                    const pctMatch = clean.match(/(\d+)%\s*→\s*(\d+)%/);
                    const sumMatch = clean.match(/Summary \((\d+) chars?\):\s*([\s\S]*)/);
                    if (hdr && pctMatch) { hdr.textContent = `🗜 ${workerName ? workerName+': ' : ''}${pctMatch[1]}% → ${pctMatch[2]}%`; hdr.style.color = '#22c55e'; }
                    else if (hdr) { hdr.textContent = `✅ ${workerName ? workerName+' ' : ''}Compacted`; hdr.style.color = '#22c55e'; }
                    if (sumMatch) {
                        const chars = sumMatch[1];
                        const summaryText = sumMatch[2].trim();
                        const charEl = document.createElement('div');
                        charEl.style.cssText = 'font-size:10px;color:#64748b;margin-top:2px';
                        charEl.textContent = `Summary: ${chars} chars`;
                        lastTool.appendChild(charEl);
                        if (summaryText) {
                            const sumEl = document.createElement('div');
                            sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;max-height:48px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                            sumEl.textContent = summaryText;
                            lastTool.appendChild(sumEl);
                            if (summaryText.split('\n').length > 3 || summaryText.length > 200) {
                                lastTool.style.cursor = 'pointer';
                                let _cExp = false;
                                lastTool.addEventListener('click', (e) => {
                                    if (e.target.tagName === 'A') return;
                                    _cExp = !_cExp;
                                    sumEl.style.maxHeight = _cExp ? 'none' : '48px';
                                    sumEl.style.overflowY = _cExp ? 'visible' : 'hidden';
                                });
                            }
                        }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__list_agents' || lastTool.dataset.toolRawName === 'mcp__orchestra__list_orchestrators') {
                    const agentLines = clean.split('\n').filter(l => l.includes('|'));
                    if (agentLines.length > 0) {
                        const PREVIEW_COUNT = 4;
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:4px';
                        for (const [i, line] of agentLines.entries()) {
                            const parts = line.split('|').map(p => p.trim());
                            const nameRaw = parts[0] || '';
                            const status = parts[1] || '';
                            const model = parts[2] || '';
                            let ctxRaw = '', taskId = '', desc = '';
                            for (let pi = 3; pi < parts.length; pi++) {
                                const p = parts[pi];
                                if (p.match(/ctx:\d+%/)) ctxRaw = p;
                                else if (p.startsWith('"')) desc = p.replace(/^"|"$/g, '');
                                else if (p && !p.startsWith('$')) taskId = p;
                            }
                            const nameClean = nameRaw.replace(/\*\*/g, '').replace(/^[^\w]*/, '').trim();
                            const icon = nameRaw.match(/[🎯⚙️🔧]/)?.[0] || '⚙️';
                            const ctxPct = parseInt(ctxRaw.match(/(\d+)%/)?.[1] || '0');
                            const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                            const isRunning = status.includes('running');
                            const row = document.createElement('div');
                            row.style.cssText = `padding:4px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${isRunning ? '#22c55e' : '#334155'}`;
                            if (i >= PREVIEW_COUNT) row.style.display = 'none';
                            row.dataset.agentRow = '1';
                            let h = `<div style="display:flex;align-items:center;gap:6px"><span style="font-size:11px;color:#e2e8f0;font-weight:600">${icon} ${DOMPurify.sanitize(nameClean)}</span><span style="margin-left:auto;font-size:10px;color:${isRunning ? '#22c55e' : '#64748b'}">${DOMPurify.sanitize(status)}</span></div>`;
                            h += `<div style="display:flex;align-items:center;gap:8px;margin-top:2px;font-size:10px;color:#64748b"><span>${DOMPurify.sanitize(model)}</span>`;
                            if (taskId) h += `<span style="color:#a78bfa;font-weight:600">#${DOMPurify.sanitize(taskId.replace(/^[A-Z]+-/, ''))}</span>`;
                            h += `<span style="display:inline-flex;align-items:center;gap:3px">ctx:<span style="color:${ctxColor}">${ctxPct}%</span></span></div>`;
                            if (desc) h += `<div style="font-size:10px;color:#64748b;font-style:italic;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(desc)}</div>`;
                            row.innerHTML = h;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (hdr) hdr.textContent += ` (${agentLines.length})`;
                        if (agentLines.length > PREVIEW_COUNT) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                            lastTool.appendChild(hint);
                            let _alExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _alExp = !_alExp;
                                container.querySelectorAll('[data-agent-row]').forEach((r, i) => {
                                    if (i >= PREVIEW_COUNT) r.style.display = _alExp ? 'block' : 'none';
                                });
                                hint.textContent = _alExp ? '▲ collapse' : `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                            });
                        }
                        addTimestamp(lastTool, ts);
                        return;
                    }
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__get_worker_logs') {
                    const lines = clean.split('\n').filter(l => l.trim());
                    let workerName = '';
                    try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                    if (hdr) { hdr.textContent = `📋 ${workerName ? workerName+': ' : ''}${lines.length} log entries`; hdr.style.color = '#a78bfa'; }
                    if (lines.length > 0) {
                        const PREVIEW_LOG = 6;
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:1px';
                        for (const [i, line] of lines.entries()) {
                            const row = document.createElement('div');
                            row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:3px;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                            row.dataset.logRow = '1';
                            if (i >= PREVIEW_LOG) row.style.display = 'none';
                            if (line.startsWith('❌')) row.style.color = '#f87171';
                            else if (line.startsWith('👤')) row.style.color = '#818cf8';
                            else if (line.startsWith('🔧')) row.style.color = '#38bdf8';
                            row.textContent = line;
                            row.title = line;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (lines.length > PREVIEW_LOG) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${lines.length - PREVIEW_LOG} more`;
                            lastTool.appendChild(hint);
                            let _logExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _logExp = !_logExp;
                                container.querySelectorAll('[data-log-row]').forEach((r, i) => { if (i >= PREVIEW_LOG) r.style.display = _logExp ? 'block' : 'none'; });
                                hint.textContent = _logExp ? '▲ collapse' : `▼ ${lines.length - PREVIEW_LOG} more`;
                            });
                        }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                const resultEl = document.createElement('div');
                resultEl.className = 'text-xs markdown-body';
                resultEl.style.cssText = 'margin-top:6px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                resultEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
                lastTool.appendChild(resultEl);
                const resLines = clean.split('\n');
                if (resLines.length > 5) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = `▼ ${resLines.length - 5} more lines`;
                    lastTool.appendChild(hint);
                    let _orchExp = false;
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        _orchExp = !_orchExp;
                        resultEl.style.maxHeight = _orchExp ? 'none' : '90px';
                        resultEl.style.overflowY = _orchExp ? 'visible' : 'hidden';
                        hint.textContent = _orchExp ? '▲ collapse' : `▼ ${resLines.length - 5} more lines`;
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'Glob') {
                let _globPattern = '';
                try { const _gp = JSON.parse(lastTool.dataset.toolContent.slice(lastTool.dataset.toolContent.indexOf(':') + 1)); _globPattern = _gp.pattern || ''; } catch {}
                const globEl = renderGlobView(_globPattern, clean);
                if (globEl) {
                    lastTool.appendChild(globEl);
                    const hdr = lastTool.querySelector('.flex.items-center');
                    if (hdr) {
                        const count = clean.split('\n').filter(l => l.trim()).length;
                        hdr.textContent = `📂 Glob: ${_globPattern || '?'} (${count})`;
                    }
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        const rest = globEl.querySelector('[data-role="read-rest"]');
                        const more = globEl.querySelector('[data-role="read-more"]');
                        if (rest && more) {
                            const exp = rest.style.display !== 'none';
                            rest.style.display = exp ? 'none' : 'block';
                            const cnt = more.dataset.count;
                            more.textContent = exp ? `▼ ${cnt} more files` : '▲ collapse';
                        }
                    });
                } else {
                    const noMatch = document.createElement('div');
                    noMatch.className = 'text-xs';
                    noMatch.style.cssText = 'margin-top:4px;color:#64748b;font-style:italic';
                    noMatch.textContent = 'No files found';
                    lastTool.appendChild(noMatch);
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName.startsWith('mcp__yougile__')) {
                const hdr = lastTool.querySelector('.flex.items-center');
                const hasErr = content.includes('error') || content.includes('Error');
                const action = lastTool.dataset.toolRawName.replace('mcp__yougile__', '');
                let parsed = null;
                try { parsed = JSON.parse(content); } catch {
                    const multiParts = content.split(/\}\s*\n\s*\{/).map((p, i, a) => (i === 0 ? p : '{' + p)).map((p, i, a) => (i < a.length - 1 ? p + '}' : p));
                    if (multiParts.length > 1) {
                        const items = multiParts.map(p => { try { return JSON.parse(p); } catch { return null; } }).filter(Boolean);
                        if (items.length > 0) parsed = items;
                    }
                }
                if (hasErr && !parsed) {
                    if (hdr) hdr.style.color = '#ef4444';
                    const errEl = document.createElement('div');
                    errEl.className = 'text-xs';
                    errEl.style.cssText = 'margin-top:4px;color:#f87171';
                    errEl.textContent = clean.slice(0, 200);
                    lastTool.appendChild(errEl);
                } else if (parsed && !Array.isArray(parsed) && !parsed.title && parsed.id && ['create_task','update_task','update_column','add_task_comment'].includes(action)) {
                    const callBody = lastTool.dataset.toolContent || '';
                    let callData = {};
                    try { const ci = callBody.indexOf(':'); callData = JSON.parse(callBody.slice(ci+1)); } catch {}
                    const callTitle = callData.title || '';
                    const status = action === 'create_task' ? `✅ Created${callTitle ? ': '+callTitle : ''}` :
                                   action === 'add_task_comment' ? '✅ Comment added' :
                                   action === 'update_column' ? `✅ Column updated${callTitle ? ': '+callTitle : ''}` :
                                   `✅ Updated${callTitle ? ': '+callTitle : ' task'}`;
                    if (hdr) { hdr.textContent = status; hdr.style.color = '#22c55e'; }
                    if (action === 'add_task_comment' && callData.comment) {
                        const commentClean = callData.comment.replace(/<br\s*\/?>/gi, '\n').replace(/<\/?b>/gi, '**').replace(/<[^>]+>/g, '');
                        const preview = commentClean.split('\n').slice(0, 3).join('\n');
                        const comEl = document.createElement('div');
                        comEl.className = 'text-xs';
                        comEl.style.cssText = 'margin-top:4px;color:#94a3b8;max-height:54px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                        comEl.textContent = preview.length < commentClean.length ? preview + '…' : preview;
                        lastTool.appendChild(comEl);
                    }
                } else {
                    const items = Array.isArray(parsed) ? parsed : (parsed && parsed.title) ? [parsed] : [];
                    if (items.length > 0) {
                        const md = items.map(t => {
                            let line = `**${t.title || 'Untitled'}**`;
                            if (t.description) {
                                const desc = t.description.replace(/<br\s*\/?>/gi, '\n').replace(/<\/?b>/gi, '**').replace(/<[^>]+>/g, '');
                                const short = desc.split('\n').slice(0, 3).join('\n');
                                line += '\n' + short;
                            }
                            return line;
                        }).join('\n\n---\n\n');
                        const resultEl = document.createElement('div');
                        resultEl.className = 'text-xs markdown-body';
                        resultEl.style.cssText = 'margin-top:6px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                        resultEl.innerHTML = DOMPurify.sanitize(marked.parse(md));
                        lastTool.appendChild(resultEl);
                        if (items.length > 1 || md.split('\n').length > 5) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#f97316;cursor:pointer';
                            hint.textContent = `▼ ${items.length > 1 ? items.length + ' items' : 'expand'}`;
                            lastTool.appendChild(hint);
                            let _ygExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _ygExp = !_ygExp;
                                resultEl.style.maxHeight = _ygExp ? 'none' : '90px';
                                resultEl.style.overflowY = _ygExp ? 'visible' : 'hidden';
                                hint.textContent = _ygExp ? '▲ collapse' : `▼ ${items.length > 1 ? items.length + ' items' : 'expand'}`;
                            });
                        }
                        if (hdr && items.length > 1) hdr.textContent += ` (${items.length})`;
                    } else if (clean.length > 5) {
                        const resultEl = document.createElement('div');
                        resultEl.className = 'text-xs';
                        resultEl.style.cssText = 'margin-top:6px;overflow-wrap:anywhere;white-space:pre-wrap;color:#cbd5e1';
                        resultEl.textContent = clean.length > 300 ? clean.slice(0, 300) + '…' : clean;
                        lastTool.appendChild(resultEl);
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'Skill') {
                const resultEl = document.createElement('div');
                resultEl.className = 'text-xs';
                resultEl.style.cssText = 'margin-top:6px;overflow-wrap:anywhere;white-space:pre-wrap;color:#cbd5e1';
                resultEl.textContent = clean.length > 300 ? clean.slice(0, 300) + '…' : clean;
                if (clean.length > 5) lastTool.appendChild(resultEl);
                addTimestamp(lastTool, ts);
                return;
            }
            const isWebFetchResult = lastTool.dataset.toolRawName === 'WebFetch' || lastTool.dataset.toolRawName === 'mcp__websearch__web_fetch';
            if (isWebFetchResult) {
                const bodyEl = document.createElement('div');
                bodyEl.className = 'text-xs markdown-body';
                bodyEl.style.cssText = 'margin-top:6px;line-height:1.5;color:#cbd5e1;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word';
                bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
                lastTool.appendChild(bodyEl);
                const fetchLines = clean.split('\n');
                if (fetchLines.length > 5) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = `▼ ${fetchLines.length - 5} more lines`;
                    lastTool.appendChild(hint);
                    let wfExpanded = false;
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        wfExpanded = !wfExpanded;
                        bodyEl.style.maxHeight = wfExpanded ? 'none' : '90px';
                        bodyEl.style.overflowY = wfExpanded ? 'visible' : 'hidden';
                        hint.textContent = wfExpanded ? '▲ collapse' : `▼ ${fetchLines.length - 5} more lines`;
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const isWebSearch = lastTool.dataset.toolRawName === 'mcp__websearch__search' ||
                                lastTool.dataset.toolRawName === 'mcp__websearch__search_web' ||
                                lastTool.dataset.toolRawName === 'WebSearch';
            if (isWebSearch) {
                const wsEl = renderWebSearchResults(content);
                if (wsEl) {
                    const sep = document.createElement('div');
                    sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                    sep.appendChild(wsEl);
                    lastTool.appendChild(sep);
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            if (lastTool.dataset.isBash) {
                const sep = document.createElement('div');
                sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                const resLines = clean.split('\n');
                const BASH_PREVIEW = 5;
                const resWrap = document.createElement('div');
                resWrap.className = 'diff-view';
                const previewPre = document.createElement('pre');
                previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
                previewPre.textContent = resLines.slice(0, BASH_PREVIEW).join('\n');
                resWrap.appendChild(previewPre);
                if (resLines.length > BASH_PREVIEW) {
                    const restPre = document.createElement('pre');
                    restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                    restPre.dataset.role = 'bash-result';
                    restPre.textContent = resLines.slice(BASH_PREVIEW).join('\n');
                    resWrap.appendChild(restPre);
                    const resHint = document.createElement('div');
                    resHint.className = 'diff-file';
                    resHint.dataset.role = 'bash-result-hint';
                    resHint.dataset.count = resLines.length - BASH_PREVIEW;
                    resHint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    resHint.textContent = `▼ ${resLines.length - BASH_PREVIEW} more lines`;
                    resWrap.appendChild(resHint);
                }
                sep.appendChild(resWrap);
                lastTool.appendChild(sep);
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.isGrep) {
                const grepEl = renderGrepResults(clean, lastTool.dataset.grepPattern);
                if (grepEl) {
                    lastTool.appendChild(grepEl);
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', () => {
                        const restEl = grepEl.querySelector('[data-role="read-rest"]');
                        const moreEl = grepEl.querySelector('[data-role="read-more"]');
                        if (restEl && moreEl) {
                            const showing = restEl.style.display !== 'none';
                            restEl.style.display = showing ? 'none' : 'block';
                            moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
                        }
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.isRead) {
                delete lastTool.dataset.lastTool;
                const readContainer = lastTool.querySelector('.diff-view');
                if (readContainer) {
                    const skeletonEl = readContainer.querySelector('[data-role="read-skeleton"]');
                    if (skeletonEl) skeletonEl.remove();
                    const readPath = readContainer.dataset.readPath || '';
                    if (/\.md$/i.test(readPath)) {
                        const mdClean = clean.replace(/^\s*\d+\t/gm, '');
                        readContainer.style.overflowX = 'hidden';
                        readContainer.style.maxWidth = '100%';
                        const mdEl = document.createElement('div');
                        mdEl.className = 'markdown-body';
                        mdEl.style.cssText = 'padding:6px 8px;font-size:11px;overflow-wrap:anywhere;word-break:break-word;overflow-x:hidden;max-width:100%;max-height:90px;overflow-y:hidden';
                        mdEl.innerHTML = DOMPurify.sanitize(marked.parse(mdClean), {ADD_TAGS: ['input'], ADD_ATTR: ['checked', 'disabled', 'type']});
                        const MD_PREVIEW_H = 90;
                        readContainer.appendChild(mdEl);
                        const moreEl = document.createElement('div');
                        moreEl.className = 'diff-file';
                        moreEl.dataset.role = 'read-more';
                        moreEl.dataset.count = '0';
                        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                        moreEl.textContent = '▼ more';
                        readContainer.appendChild(moreEl);
                        requestAnimationFrame(() => {
                            if (mdEl.scrollHeight <= MD_PREVIEW_H + 4) {
                                moreEl.style.display = 'none';
                                mdEl.style.maxHeight = 'none';
                                mdEl.style.overflowY = 'visible';
                            }
                        });
                        let mdExpanded = false;
                        const toggleMd = () => {
                            mdExpanded = !mdExpanded;
                            mdEl.style.maxHeight = mdExpanded ? 'none' : MD_PREVIEW_H + 'px';
                            mdEl.style.overflowY = mdExpanded ? 'visible' : 'hidden';
                            moreEl.textContent = mdExpanded ? '▲ collapse' : '▼ more';
                        };
                        lastTool.style.cursor = 'pointer';
                        lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleMd(); });
                        addTimestamp(lastTool, ts);
                        return;
                    }
                    if (/\.(png|jpg|jpeg|gif|webp|svg)$/i.test(readPath)) {
                        const img = document.createElement('img');
                        img.src = `/api/files/raw?path=${encodeURIComponent(readPath)}`;
                        img.loading = 'lazy';
                        img.style.cssText = 'max-height:200px;border-radius:8px;cursor:pointer;margin-top:6px;display:block';
                        img.addEventListener('click', () => openImageLightbox(img.src));
                        readContainer.appendChild(img);
                        addTimestamp(lastTool, ts);
                        return;
                    }
                    const lines = clean.split('\n').map(l => l.length > 200 ? l.slice(0, 200) + '…' : l);
                    const PREVIEW = 5;
                    const previewL = lines.slice(0, PREVIEW);
                    const restL = lines.slice(PREVIEW);
                    for (const line of previewL) {
                        const row = document.createElement('div');
                        row.className = 'diff-line diff-line-ctx';
                        const gutter = document.createElement('span');
                        gutter.className = 'diff-gutter';
                        gutter.textContent = ' ';
                        const code = document.createElement('span');
                        code.className = 'diff-code';
                        code.textContent = line;
                        row.append(gutter, code);
                        readContainer.appendChild(row);
                    }
                    if (restL.length > 0) {
                        const restEl = document.createElement('div');
                        restEl.dataset.role = 'read-rest';
                        restEl.style.display = 'none';
                        for (const line of restL) {
                            const row = document.createElement('div');
                            row.className = 'diff-line diff-line-ctx';
                            const gutter = document.createElement('span');
                            gutter.className = 'diff-gutter';
                            gutter.textContent = ' ';
                            const code = document.createElement('span');
                            code.className = 'diff-code';
                            code.textContent = line;
                            row.append(gutter, code);
                            restEl.appendChild(row);
                        }
                        readContainer.appendChild(restEl);
                        const moreEl = document.createElement('div');
                        moreEl.className = 'diff-file';
                        moreEl.dataset.role = 'read-more';
                        moreEl.dataset.count = restL.length;
                        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                        moreEl.textContent = `▼ ${restL.length} more lines`;
                        readContainer.appendChild(moreEl);
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            let _resultJsonParsed = null;
            try { _resultJsonParsed = JSON.parse(content); } catch {}
            if (_resultJsonParsed && typeof _resultJsonParsed === 'object' && !Array.isArray(_resultJsonParsed)) {
                let data = _resultJsonParsed;
                if (data.result !== undefined && Object.keys(data).length === 1) {
                    if (typeof data.result === 'string') {
                        try { data = JSON.parse(data.result); } catch { data = null; }
                    } else if (typeof data.result === 'object' && data.result !== null) {
                        data = data.result;
                    } else { data = null; }
                }
                if (data && typeof data === 'object' && !Array.isArray(data)) {
                    const hdr = lastTool.querySelector('.flex.items-center');
                    const hasErr = data.error || data.Error;
                    if (hdr && hasErr) {
                        hdr.textContent = `❌ ${DOMPurify.sanitize(String(data.error || data.Error)).slice(0, 80)}`;
                        hdr.style.color = '#ef4444';
                    } else if (hdr && !hdr.textContent.includes('✅') && !hdr.textContent.includes('❌')) {
                        hdr.textContent = hdr.textContent.replace(/⏳.*$/, '✅ Done');
                    }
                    lastTool.dataset.toolContent += '\n\n' + content;
                    const gridWrap = document.createElement('div');
                    gridWrap.style.cssText = 'margin-top:4px';
                    _renderJsonGrid(data, gridWrap);
                    lastTool.appendChild(gridWrap);
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            lastTool.dataset.toolContent += '\n\n' + content;
            const oldCopy = lastTool.querySelector('.copy-btn');
            if (oldCopy) oldCopy.remove();
            addCopyBtn(lastTool, lastTool.dataset.toolContent);

            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs result-body';
            resultEl.style.cssText = 'white-space:pre-wrap;margin-top:6px';
            resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
            lastTool.appendChild(resultEl);
            if (full) {
                const rHint = document.createElement('div');
                rHint.className = 'text-xs mt-1 result-hint';
                rHint.style.cssText = 'color:#38bdf8;cursor:pointer';
                rHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
                lastTool.appendChild(rHint);
                let rExpanded = false;
                const toggleResult = () => {
                    rExpanded = !rExpanded;
                    resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(rExpanded ? full : preview, {ADD_ATTR: ['target']});
                    rHint.textContent = rExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
                };
                lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleResult(); });
            }
            addTimestamp(lastTool, ts);
            return;
        }

        const wsStandalone = renderWebSearchResults(content);
        if (wsStandalone) {
            const sep = document.createElement('div');
            sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
            sep.appendChild(wsStandalone);
            div.appendChild(sep);
            addTimestamp(div, ts);
            const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
            _insert(div);
            if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            return;
        }

        let _standaloneJson = null;
        try { _standaloneJson = JSON.parse(content); } catch {}
        if (_standaloneJson && typeof _standaloneJson === 'object' && !Array.isArray(_standaloneJson)) {
            let sData = _standaloneJson;
            if (sData.result !== undefined && Object.keys(sData).length === 1) {
                if (typeof sData.result === 'string') { try { sData = JSON.parse(sData.result); } catch { sData = null; } }
                else if (typeof sData.result === 'object' && sData.result !== null) sData = sData.result;
                else sData = null;
            }
            if (sData && typeof sData === 'object' && !Array.isArray(sData)) {
                const gridWrap = document.createElement('div');
                gridWrap.style.cssText = 'margin-top:4px';
                _renderJsonGrid(sData, gridWrap);
                div.appendChild(gridWrap);
                addTimestamp(div, ts);
                const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
                return;
            }
        }
        const resultBody = document.createElement('div');
        resultBody.style.whiteSpace = 'pre-wrap';
        resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
        div.appendChild(resultBody);
        if (full) {
            const sHint = document.createElement('div');
            sHint.className = 'text-xs mt-1';
            sHint.style.cssText = 'color:#38bdf8;cursor:pointer';
            sHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            div.appendChild(sHint);
            let sExpanded = false;
            const toggleStandalone = () => {
                sExpanded = !sExpanded;
                resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(sExpanded ? full : preview, {ADD_ATTR: ['target']});
                sHint.textContent = sExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            };
            div.style.cursor = 'pointer';
            div.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleStandalone(); });
        }
    }
    else if (type === 'error') {
        if (/rate.?limit/i.test(content)) {
            div.textContent = '⏳ Rate limit — Anthropic временно ограничил запросы (это НЕ лимит твоей подписки). Orchestra автоматически повторит.';
            div.className = div.className.replace('text-red-400', 'text-amber-400');
        } else {
            div.textContent = content;
        }
    }
    else {
        div.innerHTML = DOMPurify.sanitize(marked.parse(content));
        const agentColor = agentColors[selectedAgent];
        if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
        renderImages(div, content);
    }

    addCopyBtn(div, content);
    addTimestamp(div, ts);
    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    _insert(div);
    while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
    if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
}


const FILE_ICONS = {
    py: '🐍', js: '📜', ts: '📜', json: '📋', md: '📝', html: '🌐', css: '🎨',
    txt: '📄', yml: '⚙️', yaml: '⚙️', toml: '⚙️', sh: '🖥', sql: '🗃',
    png: '🖼', jpg: '🖼', svg: '🖼', gif: '🖼',
};

function getFileIcon(name, isDir) {
    if (isDir) return '📁';
    const ext = name.split('.').pop().toLowerCase();
    return FILE_ICONS[ext] || '📄';
}

// Keyed by scope so each project remembers its own expanded folders independently
function _getExpandedFolders() {
    try { return new Set(JSON.parse(localStorage.getItem('expandedFolders_' + currentScope) || '[]')); } catch { return new Set(); }
}
function _saveExpandedFolder(path, expanded) {
    const set = _getExpandedFolders();
    if (expanded) set.add(path); else set.delete(path);
    localStorage.setItem('expandedFolders_' + currentScope, JSON.stringify([...set]));
}

async function loadFileTree(path, container) {
    container.innerHTML = '<div class="text-slate-600 px-2">Loading...</div>';
    try {
        const files = await api(`/api/files?path=${encodeURIComponent(path)}`);
        container.innerHTML = '';
        for (const f of files) container.appendChild(_createFileItem(f, container));
        if (files.length === 0) {
            container.innerHTML = '<div class="text-slate-600 px-2 italic">empty</div>';
        }
    } catch (e) {
        const errDiv = document.createElement('div');
        errDiv.className = 'text-red-400 px-2';
        errDiv.textContent = e.message;
        container.innerHTML = '';
        container.appendChild(errDiv);
    }
}

function _createFileItem(f, container) {
    const item = document.createElement('div');
    item.className = `file-item ${f.is_dir ? 'file-dir' : 'file-file'}`;
    item.draggable = true;
    item.dataset.path = f.path;
    item.dataset.isDir = f.is_dir;
    item.title = f.path;

    item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', f.path);
        e.dataTransfer.effectAllowed = 'copy';
    });

    if (f.is_dir) {
        const savedExpanded = _getExpandedFolders();
        let expanded = savedExpanded.has(f.path);
        const children = document.createElement('div');
        children.className = 'file-children' + (expanded ? '' : ' hidden');
        item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
        if (expanded) loadFileTree(f.path, children);
        item.addEventListener('click', async () => {
            expanded = !expanded;
            if (expanded && children.children.length === 0) {
                await loadFileTree(f.path, children);
            }
            children.classList.toggle('hidden', !expanded);
            item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
            _saveExpandedFolder(f.path, expanded);
        });
        const wrapper = document.createElement('div');
        wrapper.appendChild(item);
        wrapper.appendChild(children);
        return wrapper;
    } else {
        item.textContent = `${getFileIcon(f.name, false)} ${f.name}`;
        item.style.position = 'relative';
        const sendBtn = document.createElement('span');
        sendBtn.textContent = '➜';
        sendBtn.title = 'Send path to chat';
        sendBtn.style.cssText = 'position:absolute;right:4px;top:1px;opacity:0;cursor:pointer;font-size:11px;color:#818cf8;transition:opacity 0.15s';
        sendBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const input = $('#chat-input');
            input.value += (input.value ? '\n' : '') + f.path;
            input.focus();
            const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(f.path)
                ? `/api/files/raw?path=${encodeURIComponent(f.path)}` : f.path;
            pastedImages.push(url);
            showImagePreview(url, f.path);
        });
        item.appendChild(sendBtn);
        item.addEventListener('mouseenter', () => sendBtn.style.opacity = '1');
        item.addEventListener('mouseleave', () => sendBtn.style.opacity = '0');
        item.addEventListener('click', () => openFilePreview(f.path));
        return item;
    }
}

async function _refreshContainer(container, dirPath) {
    try {
        const files = await api(`/api/files?path=${encodeURIComponent(dirPath)}`);
        const newPaths = new Set(files.map(f => f.path));
        const existing = new Map();
        for (const child of [...container.children]) {
            const p = child.dataset?.path || child.querySelector?.('[data-path]')?.dataset?.path;
            if (p) existing.set(p, child); else child.remove();
        }
        for (const [p, el] of existing) {
            if (!newPaths.has(p)) el.remove();
        }
        let insertBefore = container.firstChild;
        for (const f of files) {
            if (existing.has(f.path)) {
                insertBefore = existing.get(f.path).nextSibling;
                continue;
            }
            const el = _createFileItem(f, container);
            container.insertBefore(el, insertBefore);
        }
    } catch {}
}

async function refreshOpenFolders() {
    const tree = $('#file-tree');
    if (!tree || !currentScope) return;
    await _refreshContainer(tree, currentScope);
    const containers = tree.querySelectorAll('.file-children:not(.hidden)');
    for (const container of containers) {
        const dirItem = container.previousElementSibling;
        if (!dirItem?.dataset?.path) continue;
        await _refreshContainer(container, dirItem.dataset.path);
    }
}

let _fileRefreshInterval = null;

function initFilePanel() {
    const tree = $('#file-tree');

    const chatInput = $('#chat-input');
    if (!chatInput.dataset.fileDropReady) {
        chatInput.dataset.fileDropReady = '1';
        chatInput.addEventListener('dragover', (e) => {
            e.preventDefault();
        });
        chatInput.addEventListener('drop', async (e) => {
            e.preventDefault();
            _hideDropHint();
            if (e.dataTransfer?.files?.length) {
                for (const file of e.dataTransfer.files) {
                    const formData = new FormData();
                    formData.append('file', file, file.name);
                    try {
                        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
                        const data = await resp.json();
                        if (data.path) {
                            chatInput.value += (chatInput.value ? '\n' : '') + data.path;
                            pastedImages.push(data.url);
                            showImagePreview(data.url, data.path);
                        }
                    } catch {}
                }
                chatInput.focus();
                return;
            }
            const path = e.dataTransfer.getData('text/plain');
            if (path) {
                chatInput.value += (chatInput.value ? '\n' : '') + path;
                chatInput.focus();
                const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(path)
                    ? `/api/files/raw?path=${encodeURIComponent(path)}` : path;
                pastedImages.push(url);
                showImagePreview(url, path);
            }
        });
    }

    if (currentScope) {
        loadFileTree(currentScope, tree);
    }
    if (_fileRefreshInterval) clearInterval(_fileRefreshInterval);
    _fileRefreshInterval = setInterval(refreshOpenFolders, 10000);
}

// === Refresh Loop ===
let refreshInProgress = false; // single-flight guard — skips if previous refresh is still in flight
async function refreshSessions() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    // Abort previous in-flight refresh so stale responses don't overwrite newer data
    if (refreshController) refreshController.abort();
    refreshController = new AbortController();
    const signal = refreshController.signal;
    // Capture scope at call time — guard below checks it didn't change while we were fetching
    const capturedScope = currentScope;

    try {
        if (!capturedScope) return;

        const [sessions, stats] = await Promise.all([
            api(`/api/sessions?scope=${encodeURIComponent(capturedScope)}`, { signal }),
            api(`/api/stats?scope=${encodeURIComponent(capturedScope)}`, { signal }),
        ]);

        if (capturedScope !== currentScope) return;
        _onServerOk();

        $('#stats-line').innerHTML = `${stats.active} active · ${stats.total_sessions} total<br><span style="color:#64748b;font-size:10px">$${stats.total_cost_usd} (w/o cache)</span>`;
        renderAgentList(sessions);

        try {
            const freshOrchs = await api('/api/orchestrators', { signal });
            for (const fo of freshOrchs) {
                const existing = orchData.find(o => o.name === fo.name);
                if (existing) {
                    const wasRunning = existing.status === 'running' || existing.any_running;
                    const nowIdle = fo.status !== 'running' && !fo.any_running;
                    if (wasRunning && nowIdle && fo.scope !== currentScope) {
                        _unreadTabs.add(fo.scope);
                    }
                    existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running;
                }
            }
            updateOrchTabDots();
        } catch {}

        if (selectedAgent) {
            const agentSession = sessions.find(s => s.name === selectedAgent);
            if (agentSession) {
                updateStopButton(agentSession.status);
                if (agentSession.status !== 'running') {
                    removeWaitingIndicator();
                }
            }
            if (!eventSource) connectSSE();
        }
    } catch (e) {
        if (e.name !== 'AbortError') { console.warn('refresh error:', e); _onServerError(); }
    } finally {
        refreshInProgress = false;
    }
}

// === API ===
// 5s timeout on all API calls — prevents hanging tabs when the server restarts mid-fetch
async function api(url, opts = {}) {
    const signal = opts.signal || AbortSignal.timeout(5000);
    const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts, signal });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
}

// === Usage Bar ===

// === Reboot Overlay ===
let _rebootOverlay = null;
let _rebootFails = 0;

function _showRebootOverlay() {
    if (_rebootOverlay) return;
    _rebootOverlay = document.createElement('div');
    _rebootOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;color:white;font-family:system-ui,sans-serif';
    const spinner = document.createElement('div');
    spinner.style.cssText = 'font-size:48px;animation:spin 1.5s linear infinite';
    spinner.textContent = '🔄';
    const msg = document.createElement('div');
    msg.style.cssText = 'font-size:18px;margin-top:16px';
    msg.textContent = 'Сервер перезагружается...';
    const sub = document.createElement('div');
    sub.style.cssText = 'font-size:14px;color:#94a3b8;margin-top:8px';
    sub.textContent = 'Автоматическое переподключение...';
    _rebootOverlay.append(spinner, msg, sub);
    document.body.appendChild(_rebootOverlay);
    const style = document.createElement('style');
    style.textContent = '@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}';
    _rebootOverlay.appendChild(style);
    _pollReconnect();
}

async function _pollReconnect() {
    while (true) {
        await new Promise(r => setTimeout(r, 2000));
        try {
            const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
            if (r.status < 502) { location.reload(); return; }
        } catch {}
    }
}

// Two consecutive failures before showing overlay — one transient error shouldn't panic the UI
function _onServerError() {
    _rebootFails++;
    if (_rebootFails >= 2) _showRebootOverlay();
}

// === Rate Limit Banner (Anthropic server-side rate_limit, not subscription) ===
let _rateLimitTimer = null;
let _rateLimitAgent = null;

function _showRateLimitBanner(agentName, retryNum, maxRetries, delaySec) {
    const banner = document.getElementById('rate-limit-banner');
    if (!banner) return;
    _rateLimitAgent = agentName;
    let remaining = delaySec;
    banner.classList.remove('hidden');
    banner.classList.add('flex');
    const render = () => {
        banner.innerHTML = `⏳ <b>Rate limit (сервер Anthropic)</b> — ${escHtml(agentName)}: повтор ${retryNum}/${maxRetries} через <b class="text-amber-100">${remaining}с</b> <span class="text-amber-400/70">· это НЕ лимит твоей подписки</span>`;
    };
    render();
    if (_rateLimitTimer) clearInterval(_rateLimitTimer);
    _rateLimitTimer = setInterval(() => {
        remaining--;
        if (remaining <= 0) { render(); _hideRateLimitBanner(); return; }
        render();
    }, 1000);
}

function _hideRateLimitBanner() {
    const banner = document.getElementById('rate-limit-banner');
    if (_rateLimitTimer) { clearInterval(_rateLimitTimer); _rateLimitTimer = null; }
    _rateLimitAgent = null;
    if (banner) { banner.classList.add('hidden'); banner.classList.remove('flex'); banner.innerHTML = ''; }
}

// Parse "rate limited — retry N/M in Xs" from status log content
function _parseRateLimitStatus(content) {
    const m = content.match(/rate limited\s*—\s*retry\s*(\d+)\/(\d+)\s*in\s*(\d+)s/i);
    if (!m) return null;
    return { retry: +m[1], max: +m[2], delay: +m[3] };
}

function _onServerOk() {
    _rebootFails = 0;
}

function initHeartbeat() {
    setInterval(async () => {
        try {
            const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
            if (r.status < 502) _onServerOk();
            else _onServerError();
        } catch { _onServerError(); }
    }, 3000);
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
    if (fileTree) fileTree.classList.toggle('hidden', tab !== 'files');
    if (tasksPanel) tasksPanel.classList.toggle('hidden', tab !== 'tasks');
    if (jobsPanel) jobsPanel.classList.toggle('hidden', tab !== 'jobs');
    _tasksTabActive = tab === 'tasks';
    _jobsTabActive = tab === 'jobs';
    if (_tasksTabActive) { loadTasks(); if (!_tasksInterval) _tasksInterval = setInterval(loadTasks, 5000); }
    else { if (_tasksInterval) { clearInterval(_tasksInterval); _tasksInterval = null; } }
    if (_jobsTabActive) { loadJobs(); if (!_jobsInterval) _jobsInterval = setInterval(loadJobs, 10000); }
    else { if (_jobsInterval) { clearInterval(_jobsInterval); _jobsInterval = null; } }
}

function openClientModal() {
    const modal = document.getElementById('client-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    _renderClientModal();
}
function closeClientModal() {
    const modal = document.getElementById('client-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}
async function _renderClientModal() {
    const body = document.getElementById('client-modal-body');
    if (!body) return;
    body.innerHTML = '<span class="text-slate-500">Loading...</span>';
    try {
        const data = await api('/api/models');
        const models = data.models || [];
        const connected = data.proxy_connected;
        const currency = document.body.dataset.currency || '$';
        let html = `<div class="flex items-center justify-between p-2.5 bg-slate-800/60 rounded-xl border border-slate-700/40 mb-3">
            <div class="flex items-center gap-2">
                <span class="text-xs font-medium ${connected ? 'text-emerald-400' : 'text-red-400'}">${connected ? '🟢 Connected' : '🔴 Offline'}</span>
            </div>
            <button id="client-refresh-btn" onclick="_refreshModels(this)" class="text-[10px] px-2.5 py-1 bg-indigo-600/40 hover:bg-indigo-600/60 rounded-lg text-indigo-300 transition-colors">🔄 Refresh</button>
        </div>`;
        if (!models.length) {
            html += `<div class="text-slate-500 italic py-6 text-center">No models available.<br>Models will appear after proxy connects.<br><span class="text-[10px] text-slate-600 mt-1 block">Auto-retry every 60s</span></div>`;
        } else {
            html += `<div class="text-[10px] text-slate-500 mb-2 uppercase tracking-wider font-bold">Models (${models.length})</div>`;
            for (const m of models) {
                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k` : '';
                const priceIn = m.price_input != null ? `${currency}${m.price_input}/M` : '';
                const priceOut = m.price_output != null ? `${currency}${m.price_output}/M` : '';
                html += `<div class="p-2.5 bg-slate-800/60 rounded-xl border border-slate-700/40 mb-2">
                    <div class="flex items-center justify-between">
                        <span class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</span>
                        ${ctx ? `<span class="text-[10px] text-indigo-400 font-mono">${ctx}</span>` : ''}
                    </div>
                    <div class="text-[10px] text-slate-500 font-mono mt-0.5">${escHtml(m.id)}</div>
                    ${priceIn || priceOut ? `<div class="text-[10px] text-slate-400 mt-1">↓ ${priceIn} &nbsp; ↑ ${priceOut}</div>` : ''}
                </div>`;
            }
        }
        html += `<div class="mt-3 p-2.5 bg-slate-800/40 rounded-xl border border-slate-700/30">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-1">Usage & Limits</div>
            <div class="text-[10px] text-slate-500 italic">Available in proxy admin panel</div>
        </div>`;
        body.innerHTML = html;
    } catch (e) {
        body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
    }
}
async function _refreshModels(btn) {
    const origText = btn.textContent;
    btn.textContent = '⏳ Loading...';
    btn.disabled = true;
    try {
        const result = await api('/api/models/refresh', { method: 'POST' });
        _modelsLoaded = false;
        await _renderClientModal();
        await loadModels();
    } catch {
        btn.textContent = '❌ Failed';
        setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 2000);
    }
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
        const [tasksResp, payResp] = await Promise.all([
            fetch(`/api/tm/tasks?scope=${encodeURIComponent(scope)}`),
            fetch('/api/tm/payments/status').catch(() => null),
        ]);
        const data = await tasksResp.json();
        const payData = payResp ? await payResp.json().catch(() => null) : null;
        renderTasksPanel(panel, data, payData);
    } catch (e) {
        panel.innerHTML = '<div class="p-2 text-slate-500">Failed to load tasks</div>';
    }
}

// === Analytics Modal ===
let _analyticsChart = null;
let _analyticsPeriod = 'week';

function openAnalyticsModal() {
    const modal = document.getElementById('analytics-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    _renderAnalyticsTabs();
    _loadAnalytics();
    document.addEventListener('keydown', _analyticsEscHandler);
}
function closeAnalyticsModal() {
    const modal = document.getElementById('analytics-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    if (_analyticsChart) { _analyticsChart.destroy(); _analyticsChart = null; }
    document.removeEventListener('keydown', _analyticsEscHandler);
}
function _analyticsEscHandler(e) { if (e.key === 'Escape') closeAnalyticsModal(); }

function _renderAnalyticsTabs() {
    const tabs = document.getElementById('analytics-tabs');
    if (!tabs) return;
    const periods = [['today', 'Today'], ['week', 'Week'], ['month', 'Month'], ['all', 'All time']];
    tabs.innerHTML = periods.map(([k, label]) =>
        `<button class="px-3 py-1.5 rounded-lg text-xs transition-colors ${k === _analyticsPeriod ? 'bg-indigo-600 text-white font-medium' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}" onclick="_analyticsPeriod='${k}';_renderAnalyticsTabs();_loadAnalytics()">${label}</button>`
    ).join('');
}

async function _loadAnalytics() {
    const body = document.getElementById('analytics-body');
    if (!body) return;
    body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
    try {
        const scope = currentScope;
        const daysMap = { today: 1, week: 7, month: 30, all: 365 };
        const days = daysMap[_analyticsPeriod];
        const [stats, daily, agents, usage] = await Promise.all([
            api(`/api/stats${scope ? '?scope=' + encodeURIComponent(scope) : ''}`),
            api(`/api/usage/daily?days=${days}`),
            api(`/api/usage/daily/agents?days=${Math.min(days, 7)}`),
            api('/api/usage').catch(() => null),
        ]);
        _renderAnalyticsBody(body, stats, daily, agents, usage);
    } catch (e) {
        body.innerHTML = `<div class="text-center text-red-400 py-8">Failed to load: ${_escHtml(e.message)}</div>`;
    }
}

function _renderAnalyticsBody(body, stats, daily, agents, usage) {
    const dailyData = Array.isArray(daily) ? daily : [];
    const agentData = Array.isArray(agents) ? agents : [];
    const today = new Date().toISOString().slice(0, 10);
    const todayRow = dailyData.find(d => d.day === today);
    const periodCost = dailyData.reduce((s, d) => s + (d.cost_usd || 0), 0);
    const periodTurns = dailyData.reduce((s, d) => s + (d.turns || 0), 0);

    let html = '';

    // Overview cards
    html += '<div class="grid grid-cols-4 gap-3 mb-4">';
    html += _analyticsCard('📅 Today', todayRow ? `$${todayRow.cost_usd.toFixed(0)}` : '$0', '#38bdf8', todayRow ? `${todayRow.turns} turns` : '');
    html += _analyticsCard('📊 Period', `$${periodCost.toFixed(0)}`, '#a78bfa', `${periodTurns} turns`);
    html += _analyticsCard('💰 All time', `$${(stats.total_cost_usd || 0).toFixed(0)}`, '#22c55e', `${stats.total_turns || 0} turns`);
    html += _analyticsCard('🤖 Active', `${stats.active || 0}`, '#f59e0b', `${stats.total_sessions || 0} total`);
    html += '</div>';

    // Rate limits
    if (usage && usage.anthropic) {
        html += '<div class="grid grid-cols-2 gap-3 mb-4">';
        const a = usage.anthropic;
        if (a.five_hour) html += _analyticsRateBar('5h Window', a.five_hour, 5 * 3600000);
        if (a.seven_day) html += _analyticsRateBar('7d Window', a.seven_day, 7 * 86400000);
        html += '</div>';
    }

    // Chart — real $/day from turn logs
    html += '<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-4 mb-4" style="height:240px"><canvas id="analytics-chart"></canvas></div>';

    // Top agents table
    const todayAgents = agentData.filter(a => a.day === today).slice(0, 20);
    const periodAgents = {};
    for (const a of agentData) {
        if (!periodAgents[a.agent]) periodAgents[a.agent] = { model: a.model, turns: 0, cost: 0 };
        periodAgents[a.agent].turns += a.turns || 0;
        periodAgents[a.agent].cost += a.cost_usd || 0;
    }
    const sortedAgents = Object.entries(periodAgents).sort((a, b) => b[1].cost - a[1].cost).slice(0, 30);

    html += '<div class="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">';
    html += '<div class="px-3 py-2 border-b border-slate-800 text-xs font-bold text-slate-400">Top Agents (period)</div>';
    html += '<div class="max-h-[200px] overflow-y-auto">';
    html += '<table class="w-full text-xs"><thead><tr class="text-slate-500 border-b border-slate-800/50"><th class="text-left px-3 py-1.5">Agent</th><th class="text-left px-3 py-1.5">Model</th><th class="text-right px-3 py-1.5">Turns</th><th class="text-right px-3 py-1.5">Cost</th></tr></thead><tbody>';
    for (const [name, a] of sortedAgents) {
        html += `<tr class="border-b border-slate-800/30 hover:bg-slate-800/30"><td class="px-3 py-1.5 font-medium text-slate-200">${_escHtml(name)}</td><td class="px-3 py-1.5 text-slate-500">${_escHtml(a.model || '?')}</td><td class="px-3 py-1.5 text-right text-slate-400">${a.turns}</td><td class="px-3 py-1.5 text-right text-emerald-400">$${a.cost.toFixed(2)}</td></tr>`;
    }
    if (!sortedAgents.length) html += '<tr><td colspan="4" class="px-3 py-3 text-center text-slate-500 italic">No data</td></tr>';
    html += '</tbody></table></div></div>';

    body.innerHTML = html;

    // Render chart
    const labels = dailyData.map(d => d.day.slice(5));
    const costs = dailyData.map(d => d.cost_usd || 0);
    const turns = dailyData.map(d => d.turns || 0);
    if (labels.length > 0 && typeof Chart !== 'undefined') {
        const ctx = document.getElementById('analytics-chart');
        if (ctx) {
            if (_analyticsChart) _analyticsChart.destroy();
            _analyticsChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        { label: 'Cost ($)', data: costs, backgroundColor: 'rgba(99,102,241,0.6)', borderColor: '#6366f1', borderWidth: 1, yAxisID: 'y', order: 2 },
                        { label: 'Turns', data: turns, type: 'line', borderColor: '#22c55e', borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y1', order: 1 },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: { labels: { color: '#94a3b8', font: { size: 10 } } },
                        tooltip: { backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155', borderWidth: 1, titleColor: '#e2e8f0', bodyColor: '#94a3b8' },
                    },
                    scales: {
                        x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
                        y: { position: 'left', title: { display: true, text: 'Cost ($)', color: '#94a3b8', font: { size: 10 } }, ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
                        y1: { position: 'right', title: { display: true, text: 'Turns', color: '#22c55e', font: { size: 10 } }, ticks: { color: '#22c55e', font: { size: 9 } }, grid: { drawOnChartArea: false } },
                    },
                },
            });
        }
    }
}

function _analyticsCard(label, value, color, subtitle) {
    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 text-center"><div class="text-[10px] text-slate-500 mb-1">${label}</div><div class="text-lg font-bold" style="color:${color}">${value}</div>${subtitle ? `<div class="text-[10px] text-slate-600 mt-0.5">${subtitle}</div>` : ''}</div>`;
}

function _analyticsRateBar(label, data, windowMs) {
    const pct = data.utilization || 0;
    const cd = _resetCountdown(data.resets_at);
    const rpNum = _resetPctNum(data.resets_at, windowMs);
    const pace = _paceIndicator(pct, data.resets_at, windowMs);
    const barColor = pct >= 80 ? '#ef4444' : pct >= 50 ? '#eab308' : '#22c55e';
    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3">
        <div class="flex items-center justify-between mb-2"><span class="text-xs font-semibold text-slate-300">${label}</span><span class="text-xs font-bold" style="color:${barColor}">${pct}%</span></div>
        <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2"><div class="h-full rounded-full transition-all" style="width:${Math.min(pct, 100)}%;background:${barColor}"></div></div>
        <div class="flex justify-between text-[10px] text-slate-500"><span>Reset: ${cd || '—'}</span>${rpNum != null ? `<span>Window: ${rpNum}%</span>` : ''}${pace ? `<span>${pace}</span>` : ''}</div>
    </div>`;
}

// === Sub-agents Modal (post-hoc telemetry + transcripts) ===
function _fmtTokens(n) {
    n = n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
}
function _fmtDuration(ms) {
    ms = ms || 0;
    if (ms < 1000) return ms + 'ms';
    const s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    const m = Math.floor(s / 60);
    const rem = Math.round(s % 60);
    if (m < 60) return `${m}m ${rem}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
}

function openSubagentsModal() {
    if (!selectedAgent || !currentScope) return;
    const modal = document.getElementById('subagents-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('subagents-modal-agent').textContent = selectedAgent;
    document.addEventListener('keydown', _subagentsEscHandler);
    _loadSubagents();
}
function closeSubagentsModal() {
    const modal = document.getElementById('subagents-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.removeEventListener('keydown', _subagentsEscHandler);
}
function _subagentsEscHandler(e) { if (e.key === 'Escape') closeSubagentsModal(); }

async function _loadSubagents() {
    const body = document.getElementById('subagents-body');
    if (!body) return;
    body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
    try {
        const sid = manager_session_id_for(selectedAgent);
        // Telemetry + transcript agent_ids in parallel. agent_id (SDK file id) != task_id,
        // so map telemetry cards → transcript ids by index (both time-ordered).
        const [data, tData] = await Promise.all([
            api(`/api/subagents/${encodeURIComponent(sid)}`),
            api(`/api/subagent-transcripts/${encodeURIComponent(sid)}`).catch(() => ({ agent_ids: [] })),
        ]);
        const subs = (data && data.subagents) || [];
        const agentIds = (tData && tData.agent_ids) || [];
        if (!subs.length) {
            body.innerHTML = '<div class="text-center text-slate-500 py-8 italic">Этот агент ещё не запускал субагентов.</div>';
            return;
        }
        body.innerHTML = subs.map((s, i) => _renderSubagentCard(s, i, agentIds[i] || '')).join('');
        // Wire transcript toggles
        body.querySelectorAll('.sa-transcript-btn').forEach(btn => {
            btn.addEventListener('click', () => _toggleTranscript(btn, sid));
        });
        body.querySelectorAll('.sa-summary-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const full = btn.nextElementSibling;
                if (full) full.classList.toggle('hidden');
                btn.textContent = full && !full.classList.contains('hidden') ? '▼ Свернуть summary' : '▶ Показать summary';
            });
        });
    } catch (e) {
        body.innerHTML = `<div class="text-center text-red-400 py-8">Ошибка: ${_escHtml(e.message)}</div>`;
    }
}

// session_id lookup — orchData/agent items carry the DB session id
function manager_session_id_for(name) {
    const el = [...document.querySelectorAll('.agent-item')].find(el => {
        const nameEl = el.querySelector('.text-xs.font-medium');
        return nameEl && nameEl.textContent === name;
    });
    return (el && el.dataset.sessionId) || name;
}

// Short, readable card title: prefer description; else first meaningful slice of a
// (possibly huge multiline bash) command — stop at first ; << newline, cap length.
function _subagentTitle(s) {
    let t = (s.description || '').trim();
    if (!t) t = (s.last_tool_name || 'Sub-agent');
    // If it's a long command dump, take up to the first structural boundary
    const boundary = t.search(/[;\n]|<</);
    if (boundary > 0 && boundary < 80) t = t.slice(0, boundary);
    t = t.replace(/\s+/g, ' ').trim();
    return t.length > 80 ? t.slice(0, 80) + '…' : t;
}

function _renderSubagentCard(s, idx, transcriptId) {
    const statusMap = {
        completed: ['🟢', '#22c55e', 'completed'],
        failed: ['🔴', '#ef4444', 'failed'],
        running: ['⏳', '#eab308', 'running'],
    };
    const [icon, color, label] = statusMap[s.status] || ['⚪', '#64748b', s.status || '?'];
    const desc = _escHtml(_subagentTitle(s));
    const taskType = s.task_type ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase" style="background:rgba(167,139,250,0.15);color:#c4b5fd">${_escHtml(s.task_type)}</span>` : '';
    // "—" for missing data (local_bash sub-agents have no usage), not misleading "0"
    const metrics = [
        `🔢 ${s.total_tokens ? _fmtTokens(s.total_tokens) : '—'}`,
        `🔧 ${s.tool_uses ? s.tool_uses : '—'}`,
        `⏱️ ${s.duration_ms ? _fmtDuration(s.duration_ms) : '—'}`,
    ];
    if (s.last_tool_name) metrics.push(`⚙️ ${_escHtml(s.last_tool_name)}`);

    let summaryBlock = '';
    if (s.summary) {
        summaryBlock = `<div class="mt-2">
            <button class="sa-summary-toggle text-[10px] text-indigo-300 hover:text-indigo-200">▶ Показать summary</button>
            <div class="hidden mt-1 p-2 bg-slate-900/60 rounded-lg text-[11px] text-slate-300 whitespace-pre-wrap break-words">${_escHtml(s.summary)}</div>
        </div>`;
    }
    let fileBlock = '';
    if (s.output_file) {
        fileBlock = `<div class="mt-1 text-[10px] text-slate-500">📄 <span class="text-emerald-400 break-all">${_escHtml(s.output_file)}</span></div>`;
    }
    const agentId = transcriptId || '';
    const transcriptBtn = agentId
        ? `<button class="sa-transcript-btn text-[10px] px-2 py-1 bg-purple-600/30 hover:bg-purple-600/50 rounded-lg text-purple-200 transition-colors" data-agent-id="${_escHtml(agentId)}" data-idx="${idx}">📜 Транскрипт</button>
           <div class="sa-transcript-panel hidden mt-2"></div>`
        : `<span class="text-[10px] text-slate-600 italic">транскрипт недоступен</span>`;

    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 mb-3" style="border-left:3px solid ${color}">
        <div class="flex items-start justify-between gap-2 mb-2">
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-sm">🤖</span>
                    <span class="text-xs font-semibold text-white break-words">${desc}</span>
                    ${taskType}
                </div>
            </div>
            <span class="text-[10px] font-mono shrink-0" style="color:${color}">${icon} ${label}</span>
        </div>
        <div class="flex items-center gap-3 flex-wrap text-[11px] text-slate-400">
            ${metrics.map(m => `<span>${m}</span>`).join('')}
        </div>
        ${fileBlock}
        ${summaryBlock}
        <div class="mt-2">${transcriptBtn}</div>
    </div>`;
}

async function _toggleTranscript(btn, sid) {
    const panel = btn.parentElement.querySelector('.sa-transcript-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
        btn.textContent = '📜 Транскрипт';
        return;
    }
    const agentId = btn.dataset.agentId;
    if (!agentId) { panel.innerHTML = '<div class="text-slate-500 italic text-[10px] p-2">Нет transcript id</div>'; panel.classList.remove('hidden'); return; }
    panel.classList.remove('hidden');
    btn.textContent = '📜 Скрыть транскрипт';
    if (panel.dataset.loaded === '1') return;  // cache — don't refetch
    panel.innerHTML = '<div class="text-slate-500 text-[10px] p-2">Загрузка транскрипта...</div>';
    try {
        const data = await api(`/api/subagent-transcript/${encodeURIComponent(sid)}/${encodeURIComponent(agentId)}?limit=200`);
        const msgs = (data && data.messages) || [];
        if (!msgs.length) {
            panel.innerHTML = '<div class="text-slate-500 italic text-[10px] p-2">Транскрипт пуст или недоступен.</div>';
            return;
        }
        panel.innerHTML = `<div class="bg-slate-950/60 rounded-lg border border-slate-800 p-2 max-h-[300px] overflow-y-auto space-y-1.5">${msgs.map(_renderTranscriptMsg).join('')}</div>`;
        panel.dataset.loaded = '1';
    } catch (e) {
        panel.innerHTML = `<div class="text-red-400 text-[10px] p-2">Ошибка: ${_escHtml(e.message)}</div>`;
    }
}

// Collapsible block for long text (bash commands, prompts, result dumps).
// Short text shows inline; long text collapses behind a <details> toggle.
function _saCollapsible(text, threshold) {
    threshold = threshold || 200;
    const clean = _escHtml(text);
    if (text.length <= threshold) {
        return `<div class="text-slate-300 whitespace-pre-wrap break-words">${clean}</div>`;
    }
    const preview = _escHtml(text.slice(0, threshold));
    return `<details class="sa-details">
        <summary class="cursor-pointer text-slate-500 hover:text-slate-300 select-none">${preview}<span class="text-purple-400"> … показать всё (${text.length} симв.)</span></summary>
        <div class="text-slate-300 whitespace-pre-wrap break-words mt-1">${clean}</div>
    </details>`;
}

function _renderTranscriptMsg(m) {
    const role = m.type === 'user' ? 'user' : m.type === 'assistant' ? 'assistant' : m.type;
    const c = m.content;
    // A tool_use block naming Task/Agent means this line spawned a nested sub-agent
    const rows = [];
    const push = (label, labelColor, bodyHtml, nested) => {
        rows.push(`<div class="text-[10px] leading-relaxed ${nested ? 'ml-3 pl-2 border-l-2 border-purple-800/60' : ''}">
            <span style="color:${labelColor};font-weight:600">${label}</span>
            <div class="pl-2 border-l border-slate-800 mt-0.5">${bodyHtml}</div>
        </div>`);
    };

    if (typeof c === 'string') {
        if (!c.trim()) return '';
        push(role === 'user' ? '🔧 tool result' : '🤖 субагент',
             role === 'user' ? '#38bdf8' : '#a78bfa', _saCollapsible(c));
    } else if (Array.isArray(c)) {
        for (const block of c) {
            if (!block || typeof block !== 'object') {
                const t = String(block); if (t.trim()) push('•', '#64748b', _saCollapsible(t));
                continue;
            }
            if (block.type === 'text') {
                if ((block.text || '').trim()) push('🤖 субагент', '#a78bfa', _saCollapsible(block.text));
            } else if (block.type === 'tool_use') {
                const name = block.name || 'tool';
                const isNested = /^(Task|Agent)$/i.test(name);
                const args = JSON.stringify(block.input || {});
                const bodyHtml = _saCollapsible(args, 120);
                push(`${isNested ? '🤖' : '🔧'} ${_escHtml(name)}`, isNested ? '#c4b5fd' : '#eab308', bodyHtml, isNested);
            } else if (block.type === 'tool_result') {
                const rc = block.content;
                const txt = typeof rc === 'string' ? rc : JSON.stringify(rc);
                push('📎 результат', '#64748b', _saCollapsible(txt, 200));
            } else {
                push('•', '#64748b', _saCollapsible(JSON.stringify(block), 200));
            }
        }
    } else if (c) {
        push('•', '#64748b', _saCollapsible(JSON.stringify(c)));
    }
    return rows.join('');
}

function renderTasksPanel(panel, data, payData) {
    const tasks = data.tasks || [];
    const grouped = {};
    for (const t of tasks) { (grouped[t.status] ||= []).push(t); }

    let html = '';
    html += '<div class="px-2 py-1.5 border-b border-slate-800/50 space-y-0.5">';
    if (payData && payData.balance_display) {
        html += `<div class="flex justify-between"><span class="text-slate-500">💰 Balance:</span><span class="text-emerald-400 font-mono">${escHtml(payData.balance_display)}</span></div>`;
    }
    html += `<div class="flex justify-between"><span class="text-slate-500">📊 Debt:</span><span class="text-amber-400 font-mono">${escHtml(data.total_debt || '0')}</span></div>`;
    html += '</div>';

    if (tasks.length === 0) {
        html += '<div class="p-4 text-center text-slate-600 italic">No tasks yet</div>';
        panel.innerHTML = html;
        return;
    }

    const _PRI_COLOR = {0:'#ef4444',1:'#f97316',2:'#eab308',3:'#22c55e'};
    for (const status of STATUS_ORDER) {
        const group = grouped[status];
        if (!group || group.length === 0) continue;
        const isCollapsed = _taskCollapsed[status] ?? COLLAPSED_DEFAULT.has(status);
        const dot = STATUS_COLORS[status] || 'bg-slate-400';
        const label = STATUS_LABELS[status] || status.toUpperCase();
        const arrow = isCollapsed ? '▸' : '▾';
        let suffix = '';
        if (status === 'done') {
            const debt = group.reduce((s, t) => s + (parseInt(t.debt) || 0), 0);
            if (debt > 0) suffix = ` → ${debt}k`;
        }
        html += '<div class="mt-1">';
        html += `<div class="px-2 py-1 flex items-center gap-1.5 cursor-pointer hover:bg-slate-800/30 rounded select-none" onclick="toggleTaskGroup('${status}')">`;
        html += `<span class="text-[10px]">${arrow}</span>`;
        html += `<span class="w-1.5 h-1.5 rounded-full ${dot} shrink-0"></span>`;
        html += `<span class="text-slate-400 font-bold flex-1">${label} (${group.length})</span>`;
        if (suffix) html += `<span class="text-amber-400 font-mono">${suffix}</span>`;
        html += '</div>';
        if (!isCollapsed) {
            for (const t of group) {
                const par = t.par;
                const priceInfo = t.price !== '0' ? (t.paid !== '0' ? `${t.paid}/${t.price}` : t.price) : '';
                const priColor = _PRI_COLOR[t.priority];
                html += `<div class="task-item flex items-center gap-1.5 px-2 py-0.5 hover:bg-slate-800/50 rounded cursor-pointer" style="position:relative" data-par="${par}" onclick="showTaskDetail('${par}')">`;
                if (priColor) html += `<span style="width:8px;height:8px;border-radius:50%;background:${priColor};flex-shrink:0"></span>`;
                html += `<span class="text-slate-600 font-mono shrink-0 w-6 text-right">${par}</span>`;
                html += `<span class="truncate flex-1 ${t.status === 'paid' ? 'text-slate-500' : ''}">${escHtml(t.title)}</span>`;
                if (priceInfo) html += `<span class="text-amber-400/70 shrink-0 font-mono">${priceInfo}</span>`;
                html += `<span class="task-inject-btn" onclick="event.stopPropagation();injectTask('${par}')" title="Insert #${par} into chat">📩</span>`;
                html += '</div>';
            }
        }
        html += '</div>';
    }
    panel.innerHTML = html;
}

function toggleTaskGroup(status) {
    const current = _taskCollapsed[status] ?? COLLAPSED_DEFAULT.has(status);
    _taskCollapsed[status] = !current;
    loadTasks();
}

function injectTask(par) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    const ref = `[#${par}]`;
    if (!input.value.includes(`#${par}`)) {
        input.value = (input.value ? input.value + ' ' : '') + ref;
        input.focus();
    }
}

async function showTaskDetail(par) {
    try {
        const scope = currentScope ? `?scope=${encodeURIComponent(currentScope)}` : '';
        const r = await fetch(`/api/tm/tasks/${par}${scope}`);
        const t = await r.json();
        if (t.error) return;
        const modal = document.getElementById('prompt-modal');
        const nameEl = document.getElementById('prompt-modal-name');
        const bodyEl = document.getElementById('prompt-modal-body');
        if (!modal || !nameEl || !bodyEl) return;
        nameEl.textContent = '#' + t.par + ' ' + t.title;
        let html = '<div class="space-y-3">';
        html += '<div class="grid grid-cols-2 gap-2 text-xs">';
        html += `<div><span class="text-slate-500">Status:</span> <span class="font-bold">${t.status}</span></div>`;
        html += `<div><span class="text-slate-500">Price:</span> <span class="text-amber-400">${t.price_rub > 0 ? (t.price_rub/1000)+'k '+CUR : '—'}</span></div>`;
        html += `<div><span class="text-slate-500">Paid:</span> ${(t.paid_rub||0)/1000}/${(t.price_rub||0)/1000}k</div>`;
        html += `<div><span class="text-slate-500">Debt:</span> <span class="text-red-400">${t.debt_rub > 0 ? (t.debt_rub/1000)+'k '+CUR : '0'}</span></div>`;
        html += `<div><span class="text-slate-500">Assignee:</span> ${escHtml(t.assignee || '—')}</div>`;
        const _PRI = {0:'🔴 Critical',1:'🟠 High',2:'🟡 Medium',3:'🟢 Low'};
        html += `<div><span class="text-slate-500">Priority:</span> ${_PRI[t.priority] || 'Medium'}</div>`;
        html += `<div><span class="text-slate-500">Project:</span> ${escHtml(t.project)}</div>`;
        html += `<div><span class="text-slate-500">Created:</span> ${(t.created_at||'').slice(0,10)}</div>`;
        if (t.updated_at) html += `<div><span class="text-slate-500">Updated:</span> ${t.updated_at.slice(0,10)}</div>`;
        if (t.completed_at) html += `<div><span class="text-slate-500">Done:</span> ${t.completed_at.slice(0,10)}</div>`;
        if (t.paid_at) html += `<div><span class="text-slate-500">Paid at:</span> ${t.paid_at.slice(0,10)}</div>`;
        html += '</div>';
        if (t.description) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">DESCRIPTION</div>';
            html += `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(t.description))}</div></div>`;
        }
        if (t.payments && t.payments.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">PAYMENTS</div>';
            for (const p of t.payments) { html += `<div class="text-xs">• ${p.date}: +${p.amount/1000}k (payment #${p.payment_id})</div>`; }
            html += '</div>';
        }
        const commits = t.commits || t.git_commits || [];
        if (commits.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">COMMITS</div>';
            for (const c of commits) {
                if (typeof c === 'string') { html += `<div class="text-xs font-mono">${escHtml(c.slice(0,60))}</div>`; continue; }
                const hash = (c.hash || '').slice(0, 7);
                const msg = (c.message || '').length > 50 ? c.message.slice(0, 50) + '…' : (c.message || '');
                const date = (c.date || '').slice(0, 10);
                const ins = c.insertions || 0; const del = c.deletions || 0; const files = c.files || 0;
                html += `<div style="display:flex;align-items:center;gap:6px;font-size:11px;line-height:1.6"><span style="color:#a78bfa;font-family:monospace;flex-shrink:0">${escHtml(hash)}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e2e8f0">${escHtml(msg)}</span><span style="color:#64748b;flex-shrink:0">${escHtml(date)}</span><span style="flex-shrink:0"><span style="color:#22c55e">+${ins}</span>/<span style="color:#ef4444">-${del}</span></span><span style="color:#64748b;flex-shrink:0">${files}f</span></div>`;
            }
            html += '</div>';
        }
        const sys = [];
        if (t.yougile_task_id) sys.push(`yougile: ${t.yougile_task_id}`);
        if (t.sync_revision) sys.push(`sync rev: ${t.sync_revision}`);
        if (t.worker_session_id) sys.push(`worker: ${t.worker_session_id}`);
        if (sys.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">SYSTEM</div>';
            html += `<div class="text-[10px] text-slate-600 font-mono">${sys.join(' · ')}</div></div>`;
        }
        html += '</div>';
        bodyEl.innerHTML = html;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    } catch (e) { console.error('Task detail error:', e); }
}

// === Jobs Panel ===
const _JOB_ICONS = { timer: '⏰', file: '📄', command: '🖥️', ssh: '🔗', run: '▶️' };
const _JOB_STATUS = { active: '🟢', triggered: '✅', expired: '⏰', cancelled: '❌', failed: '❌' };

async function loadJobs() {
    const panel = document.getElementById('jobs-panel');
    if (!panel) return;
    try {
        const scope = currentScope || '';
        const resp = await fetch(`/api/bg/jobs?scope=${encodeURIComponent(scope)}`);
        const jobs = await resp.json();
        renderJobsPanel(panel, Array.isArray(jobs) ? jobs : (jobs.jobs || []));
    } catch (e) {
        panel.innerHTML = '<div class="p-2 text-slate-500">Failed to load jobs</div>';
    }
}

function _timeLeft(expiresAt) {
    if (!expiresAt) return '';
    const diff = new Date(expiresAt) - Date.now();
    if (diff <= 0) return 'expired';
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

let _jobsTimerInterval = null;
const _expandedJobs = new Set();
function renderJobsPanel(panel, jobs) {
    if (_jobsTimerInterval) { clearInterval(_jobsTimerInterval); _jobsTimerInterval = null; }
    if (jobs.length === 0) {
        panel.innerHTML = '<div class="p-4 text-center text-slate-600 italic">No background jobs</div>';
        return;
    }
    const active = jobs.filter(j => j.status === 'active');
    const done = jobs.filter(j => j.status !== 'active');
    panel.innerHTML = '';
    if (active.length > 0) {
        const hdr = document.createElement('div');
        hdr.className = 'px-2 py-1 text-slate-400 font-bold text-[10px]';
        hdr.textContent = `ACTIVE (${active.length})`;
        panel.appendChild(hdr);
        for (const j of active) panel.appendChild(_createJobItem(j));
    }
    if (done.length > 0) {
        const hdr = document.createElement('div');
        hdr.className = 'px-2 py-1 mt-1 text-slate-500 font-bold text-[10px]';
        hdr.textContent = 'COMPLETED';
        panel.appendChild(hdr);
        for (const j of done.slice(0, 10)) panel.appendChild(_createJobItem(j));
    }
    if (active.length > 0) {
        _jobsTimerInterval = setInterval(() => {
            panel.querySelectorAll('[data-job-elapsed]').forEach(el => {
                const created = el.dataset.jobElapsed;
                if (created) el.textContent = _elapsed(created);
            });
            panel.querySelectorAll('[data-job-expires]').forEach(el => {
                const exp = el.dataset.jobExpires;
                if (exp) el.textContent = _timeLeft(exp);
            });
        }, 1000);
    }
}

function _elapsed(isoStr) {
    const ms = Date.now() - new Date(isoStr).getTime();
    if (ms < 0) return '0s';
    const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
    if (h > 0) return `${h}h ${m % 60}m`;
    if (m > 0) return `${m}m ${s % 60}s`;
    return `${s}s`;
}

function _createJobItem(j) {
    const icon = _JOB_ICONS[j.type] || '⚙️';
    const statusIcon = _JOB_STATUS[j.status] || '⚪';
    const target = j.target_name || '';
    const msg = j.message ? j.message.slice(0, 50) : '';
    let cfg = {};
    try { cfg = JSON.parse(j.config || '{}'); } catch {}

    const wrap = document.createElement('div');
    const row = document.createElement('div');
    row.className = 'flex items-center gap-1.5 px-2 py-1 hover:bg-slate-800/50 rounded text-xs cursor-pointer';
    row.style.position = 'relative';

    let timerHtml = '';
    if (j.status === 'active' && j.created_at) {
        timerHtml = `<span data-job-elapsed="${j.created_at}" style="color:#38bdf8;font-size:10px;font-family:monospace">${_elapsed(j.created_at)}</span>`;
    }
    if (j.status === 'active' && j.expires_at) {
        timerHtml += `<span data-job-expires="${j.expires_at}" style="color:#64748b;font-size:10px;font-family:monospace">${_timeLeft(j.expires_at)}</span>`;
    }
    const cancelBtn = j.status === 'active' ? `<span class="job-cancel-btn" title="Cancel job">✕</span>` : '';

    row.innerHTML = `<span>${icon}</span><span class="flex-1 truncate"><span style="color:#e2e8f0">${escHtml(target)}</span>${msg ? ' <span style="color:#64748b">'+escHtml(msg)+'</span>' : ''}</span>${timerHtml}<span>${statusIcon}</span>${cancelBtn}`;

    const cancelEl = row.querySelector('.job-cancel-btn');
    if (cancelEl) cancelEl.addEventListener('click', (e) => { e.stopPropagation(); cancelJob(j.id); });

    const detail = document.createElement('div');
    detail.style.cssText = 'display:none;padding:4px 8px 6px 24px;font-size:10px;color:#64748b;line-height:1.6';
    const _dr = (k, v) => v ? `<div><span style="color:#475569">${k}:</span> <span style="color:#94a3b8">${escHtml(String(v))}</span></div>` : '';
    let dh = _dr('Type', j.type);
    dh += _dr('Target', target);
    dh += _dr('Status', j.status);
    if (cfg.command) dh += `<div><span style="color:#475569">Command:</span> <pre style="margin:2px 0;padding:3px 6px;background:#0d1117;border-radius:4px;font-size:10px;color:#cbd5e1;white-space:pre-wrap;word-break:break-all;max-height:60px;overflow-y:auto">${escHtml(cfg.command)}</pre></div>`;
    if (cfg.pattern) dh += _dr('Pattern', cfg.pattern);
    if (cfg.path) dh += _dr('Path', cfg.path);
    if (cfg.host) dh += _dr('Host', cfg.host);
    if (cfg.interval_seconds) dh += _dr('Interval', `${cfg.interval_seconds}s`);
    dh += _dr('Message', j.message);
    if (j.created_at) dh += _dr('Created', new Date(j.created_at).toLocaleString());
    if (j.expires_at) dh += _dr('Expires', new Date(j.expires_at).toLocaleString());
    if (j.output) dh += `<div><span style="color:#475569">Output:</span> <pre style="margin:2px 0;padding:3px 6px;background:#0d1117;border-radius:4px;font-size:10px;color:#cbd5e1;white-space:pre-wrap;word-break:break-all;max-height:80px;overflow-y:auto">${escHtml(String(j.output).slice(0, 500))}</pre></div>`;
    detail.innerHTML = dh;

    const isExpanded = _expandedJobs.has(j.id);
    detail.style.display = isExpanded ? 'block' : 'none';
    row.addEventListener('click', () => {
        const show = detail.style.display === 'none';
        detail.style.display = show ? 'block' : 'none';
        if (show) _expandedJobs.add(j.id); else _expandedJobs.delete(j.id);
    });

    wrap.appendChild(row);
    wrap.appendChild(detail);
    return wrap;
}

async function cancelJob(id) {
    try {
        await fetch(`/api/bg/jobs/${id}`, { method: 'DELETE' });
        loadJobs();
    } catch (e) { console.warn('Cancel job failed:', e); }
}

// ── Proxy Manager ──

let _proxyDropdownOpen = false;

function initProxy() {
    const btn = $('#proxy-btn');
    const dropdown = $('#proxy-dropdown');
    if (!btn || !dropdown) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _proxyDropdownOpen = !_proxyDropdownOpen;
        dropdown.classList.toggle('hidden', !_proxyDropdownOpen);
        if (_proxyDropdownOpen) loadProxyList();
    });
    document.addEventListener('click', (e) => {
        if (_proxyDropdownOpen && !dropdown.contains(e.target) && e.target !== btn) {
            _proxyDropdownOpen = false;
            dropdown.classList.add('hidden');
        }
    });
    $('#proxy-check-all')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const btn = e.target;
        btn.textContent = '...';
        try {
            const data = await (await fetch('/api/proxy/list')).json();
            const ids = (data.proxies || []).map(p => p.id);
            await Promise.all(ids.map(id => fetch(`/api/proxy/check/${id}`, {method:'POST'})));
            await loadProxyList();
        } finally { btn.textContent = 'Check All'; }
    });
    loadProxyList();
}

async function loadProxyList() {
    try {
        const data = await (await fetch('/api/proxy/list')).json();
        const list = $('#proxy-list');
        if (!list) return;
        list.innerHTML = '';
        const proxies = data.proxies || [];
        if (!proxies.length) {
            list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No proxies configured.<br>Set PROXY_LIST in .env</div>';
            return;
        }
        for (const p of proxies) {
            const el = document.createElement('div');
            el.className = `flex items-center gap-2 px-2.5 py-2 rounded-lg transition-colors ${p.active ? 'bg-indigo-900/40 border border-indigo-500/50' : 'bg-slate-800/50 border border-slate-700/50 hover:bg-slate-700/50'}`;
            const isRateLimited = p.ok === false && /429|rate.?limit/i.test(String(p.error || ''));
            const status = isRateLimited ? '⏳' : p.ok === true ? '🟢' : p.ok === false ? '🔴' : '⚪';
            const statusTitle = isRateLimited ? 'Rate limit (429) — проверь позже' : p.ok === true ? 'Живой' : p.ok === false ? 'Мёртвый' : 'Не проверен';
            const flag = p.flag || '🏳️';
            const location = p.city ? `${p.city}, ${p.country || ''}` : p.country || '';
            el.innerHTML = `
                <span class="text-sm" title="${statusTitle}">${status}</span>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5">
                        <span class="text-sm">${flag}</span>
                        <span class="proxy-name text-xs font-medium text-white truncate">${escHtml(p.name)}</span>
                        ${p.active ? '<span class="text-[9px] px-1 py-0.5 bg-indigo-500/30 text-indigo-300 rounded shrink-0">ACTIVE</span>' : ''}
                    </div>
                    ${location ? `<div class="text-[10px] text-slate-400 truncate">${escHtml(location)}</div>` : ''}
                    <div class="proxy-url-line text-[9px] text-slate-600 truncate cursor-pointer hidden" title="Показать URL">${escHtml(p.url)}</div>
                    ${p.error ? `<div class="text-[10px] text-red-400 truncate">${escHtml(String(p.error).slice(0, 60))}</div>` : ''}
                </div>
                <div class="flex gap-1 shrink-0">
                    <button class="proxy-check-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300" data-id="${p.id}" title="Проверить живость">🔍</button>
                    ${!p.active ? `<button class="proxy-select-btn text-[10px] px-2 py-0.5 bg-indigo-600 hover:bg-indigo-500 rounded text-white font-medium" data-id="${p.id}" data-name="${escHtml(p.name)}" title="Выбрать этот прокси">Выбрать</button>` : ''}
                </div>
            `;
            // URL revealed on click of the name area — hidden by default to keep UI clean
            el.querySelector('.proxy-name')?.addEventListener('click', (e) => {
                e.stopPropagation();
                el.querySelector('.proxy-url-line')?.classList.toggle('hidden');
            });
            list.appendChild(el);
        }
        list.querySelectorAll('.proxy-check-btn').forEach(b => {
            b.addEventListener('click', async (e) => {
                e.stopPropagation();
                b.textContent = '⏳';
                try {
                    await fetch(`/api/proxy/check/${b.dataset.id}`, {method:'POST'});
                    await loadProxyList();
                } catch(err) { b.textContent = '❌'; }
            });
        });
        list.querySelectorAll('.proxy-select-btn').forEach(b => {
            b.addEventListener('click', async (e) => {
                e.stopPropagation();
                b.textContent = '⏳'; b.disabled = true;
                try {
                    const resp = await fetch('/api/proxy/set-env', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id: b.dataset.id }),
                    });
                    const data = await resp.json();
                    if (!resp.ok || data.ok === false) throw new Error(data.error || 'set-env failed');
                    _showProxyRestartBanner(b.dataset.name, data.wrote);
                } catch (err) {
                    b.textContent = '❌'; b.disabled = false;
                    console.warn('proxy set-env failed:', err);
                }
            });
        });
        const active = proxies.find(p => p.active);
        if (active) {
            $('#proxy-flag').textContent = active.flag || '🌐';
            $('#proxy-ip').textContent = active.ip || '';
        }
    } catch (e) { console.warn('loadProxyList failed:', e); }
}

function _showProxyRestartBanner(name, wroteUrl) {
    const banner = $('#proxy-restart-banner');
    const msg = $('#proxy-restart-msg');
    if (!banner || !msg) return;
    msg.innerHTML = `<b>${escHtml(name)}</b> записан в .env${wroteUrl ? ` <span class="text-amber-400/60">(${escHtml(wroteUrl)})</span>` : ''}. Нажми Рестарт чтобы применить.`;
    banner.classList.remove('hidden');
    const btn = $('#proxy-restart-btn');
    if (btn && !btn._wired) {
        btn._wired = true;
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            btn.textContent = '⏳ Рестарт...'; btn.disabled = true;
            try { await api('/api/restart', { method: 'POST' }); } catch {}
            setTimeout(() => location.reload(), 3000);
        });
    }
}

// ── Profiles Manager (редактор реестра профилей Claude) ──

let _profilesDropdownOpen = false;

function initProfilesManager() {
    const btn = $('#profiles-btn');
    const dropdown = $('#profiles-dropdown');
    if (!btn || !dropdown) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _profilesDropdownOpen = !_profilesDropdownOpen;
        dropdown.classList.toggle('hidden', !_profilesDropdownOpen);
        if (_profilesDropdownOpen) loadProfilesList();
    });
    document.addEventListener('click', (e) => {
        if (_profilesDropdownOpen && !dropdown.contains(e.target) && e.target !== btn) {
            _profilesDropdownOpen = false;
            dropdown.classList.add('hidden');
        }
    });
    $('#profile-add-btn')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const name = $('#profile-new-name').value.trim();
        const config_dir = $('#profile-new-dir').value.trim();
        const errEl = $('#profile-error');
        errEl.classList.add('hidden');
        if (!name) { errEl.textContent = 'name required'; errEl.classList.remove('hidden'); return; }
        try {
            const res = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ name, config_dir }) });
            $('#profile-new-name').value = '';
            $('#profile-new-dir').value = '';
            await loadProfilesList();
            // Мягкое предупреждение: профиль сохранён, но config_dir не существует.
            if (res && res.warning) {
                errEl.textContent = res.warning;
                errEl.classList.remove('hidden');
            }
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
}

async function loadProfilesList() {
    try {
        const profiles = await api('/api/profiles');
        const list = $('#profiles-list');
        if (!list) return;
        list.innerHTML = '';
        if (!profiles.length) {
            list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No profiles.</div>';
            return;
        }
        for (const p of profiles) {
            const el = document.createElement('div');
            el.className = 'flex items-center gap-2 px-2.5 py-2 rounded-lg bg-slate-800/50 border border-slate-700/50';
            const isPersonal = p.name === 'personal';
            el.innerHTML = `
                <div class="flex-1 min-w-0">
                    <div class="text-xs font-medium text-white truncate">${escHtml(p.name)}</div>
                    <div class="text-[10px] text-slate-500 truncate">${escHtml(p.config_dir || 'env процесса')}</div>
                </div>
                ${isPersonal ? '' : `<button class="profile-del-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-red-900/60 rounded text-slate-400 hover:text-red-400 shrink-0" data-name="${escHtml(p.name)}" title="Delete">✕</button>`}
            `;
            list.appendChild(el);
        }
        list.querySelectorAll('.profile-del-btn').forEach(b => {
            b.addEventListener('click', async (e) => {
                e.stopPropagation();
                const errEl = $('#profile-error');
                errEl.classList.add('hidden');
                b.textContent = '⏳';
                try {
                    await api(`/api/profiles/${encodeURIComponent(b.dataset.name)}`, { method: 'DELETE' });
                    await loadProfilesList();
                } catch (err) {
                    b.textContent = '✕';
                    errEl.textContent = err.message;
                    errEl.classList.remove('hidden');
                }
            });
        });
    } catch (e) { console.warn('loadProfilesList failed:', e); }
}
