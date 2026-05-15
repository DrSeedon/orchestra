const MAX_CHAT_NODES = 500;
let currentScope = null;
let selectedAgent = null;
let chatLogs = {};
let localMessages = new Set();
let pendingUserMsgs = [];
let pendingBubble = null;
let uiDebounceTimer = null;
let refreshController = null;
const UI_DEBOUNCE_MS = 2500;
let scrollAfterLoad = true;
let drafts = {};

window.compactMode = localStorage.getItem('compactToolMode') === 'true';

const $ = (s) => document.querySelector(s);

DOMPurify.addHook('uponSanitizeElement', (node) => {
    if (['STYLE', 'HTML', 'HEAD', 'BODY', 'META', 'LINK', 'TITLE', 'SCRIPT'].includes(node.tagName)) node.remove();
});

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
        $('#orch-cwd').focus();
    });
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
    $('#delete-orch-btn').addEventListener('click', deleteOrchestrator);
    $('#restart-btn').addEventListener('click', restartServer);
    $('#orch-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
    $('#orch-cwd').addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
    $('#view-prompt-btn').addEventListener('click', openPromptModal);
    $('#compact-btn').addEventListener('click', compactAgent);
    $('#prompt-modal-close').addEventListener('click', closePromptModal);
    $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); } });
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
            if (chatLogs[selectedAgent]) { chatLogs[selectedAgent].lastId = 0; chatLogs[selectedAgent].firstId = null; }
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

function connectSSE() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (!selectedAgent || !currentScope) return;
    const lastId = chatLogs[selectedAgent]?.lastId || 0;
    const limitParam = lastId === 0 ? '&limit=100' : '';
    const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
    eventSource = new EventSource(url);
    eventSource.onmessage = (event) => {
        try {
            const l = JSON.parse(event.data);
            const isLocal = l.type === 'user_message' && (localMessages.has(l.content) || [...localMessages].some(m => l.content.endsWith(m)));
            if (isLocal) {
                localMessages.delete(l.content);
                for (const m of localMessages) { if (l.content.endsWith(m)) { localMessages.delete(m); break; } }
                if (pendingBubble) { pendingBubble.remove(); pendingBubble = null; pendingUserMsgs = []; }
                addChatEntry(l.type, l.content, l.ts);
            } else {
                addChatEntry(l.type, l.content, l.ts);
            }
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
            if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
            if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                chatLogs[selectedAgent].firstId = l.id;
                updateLoadMoreBtn();
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
        setTimeout(connectSSE, 2000);
    };
}

function updateLoadMoreBtn() {
    const chat = $('#chat');
    const existing = $('#load-more-btn');
    const firstId = chatLogs[selectedAgent]?.firstId;
    if (!firstId || firstId <= 1) {
        if (existing) existing.remove();
        return;
    }
    if (existing) return;
    const btn = document.createElement('div');
    btn.id = 'load-more-btn';
    btn.className = 'text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
    btn.textContent = '▲ Load 500 more';
    btn.addEventListener('click', loadMoreLogs);
    chat.prepend(btn);
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
        const models = await api('/api/models');
        const select = $('#orch-model');
        select.innerHTML = '';
        for (const m of models) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = `${m.name} (${m.id})`;
            select.appendChild(opt);
        }
    } catch {}
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

function _promptSection(title, color, content) {
    if (!content || !content.trim()) return '';
    const rendered = DOMPurify.sanitize(marked.parse(content));
    return `<div style="margin-bottom:16px"><div style="font-size:11px;font-weight:700;color:${color};margin-bottom:6px;padding:3px 8px;border-radius:4px;background:rgba(0,0,0,0.3);display:inline-block">${title}</div><div class="markdown-body" style="padding-left:4px">${rendered}</div></div>`;
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

async function openPromptModal() {
    if (!selectedAgent || !currentScope) return;
    const modal = $('#prompt-modal');
    const body = $('#prompt-modal-body');
    $('#prompt-modal-name').textContent = selectedAgent;
    body.innerHTML = '<span class="text-slate-500 text-xs">Loading...</span>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    try {
        const data = await api(`/api/sessions/${selectedAgent}/prompt?scope=${encodeURIComponent(currentScope)}`);
        if (!data.system_prompt || !data.system_prompt.trim()) {
            body.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
        } else if (data.base || data.role) {
            body.innerHTML =
                _promptSection('📦 Platform (base.md)', '#64748b', data.base) +
                _promptSection('🎭 Role', '#818cf8', data.role) +
                _promptSection('✨ Custom', '#22c55e', data.custom);
            if (!data.custom) {
                body.innerHTML += '<div style="font-size:10px;color:#475569;font-style:italic;margin-top:8px">No custom system prompt</div>';
            }
        } else {
            body.innerHTML = DOMPurify.sanitize(marked.parse(data.system_prompt));
        }
    } catch (e) {
        const errSpan = document.createElement('span');
        errSpan.className = 'text-red-400 text-xs';
        errSpan.textContent = e.message;
        body.innerHTML = '';
        body.appendChild(errSpan);
    }
}

async function openFilePreview(path) {
    const modal = $('#file-preview-modal');
    const pathEl = $('#file-preview-path');
    const contentEl = $('#file-preview-content');
    pathEl.textContent = path;
    contentEl.textContent = 'Loading…';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
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
            contentEl.className = 'flex-1 overflow-auto text-xs text-slate-300 markdown-body p-4';
            contentEl.style.whiteSpace = '';
            contentEl.style.overflowX = 'hidden';
            contentEl.style.wordWrap = '';
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
            contentEl.innerHTML = DOMPurify.sanitize(marked.parse(data.content, { renderer }), { ADD_ATTR: ['loading'] });
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
                contentEl.className = 'flex-1 overflow-auto text-xs p-4 markdown-body';
                contentEl.style.cssText = '';
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
                contentEl.className = 'flex-1 overflow-auto text-xs p-4';
                contentEl.style.cssText = '';
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
                contentEl.className = 'flex-1 overflow-auto text-xs p-4';
                contentEl.style.cssText = '';
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
                contentEl.className = 'flex-1 overflow-auto text-xs p-4 text-slate-300';
                contentEl.style.whiteSpace = 'pre';
                contentEl.style.overflowX = 'auto';
                contentEl.style.wordWrap = 'normal';
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
}

function initFilePreviewModal() {
    const modal = $('#file-preview-modal');
    if (!modal) return;
    $('#file-preview-close').addEventListener('click', closeFilePreview);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeFilePreview(); });
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
    const errEl = $('#orch-error');
    if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
    const btn = $('#create-orch-btn');
    btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
    try {
        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, is_orchestrator: true }) });
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
        orchData = await api('/api/orchestrators');
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

function renderOrchTabs(sorted) {
    const tabs = $('#orch-tabs');
    tabs.innerHTML = '';
    const ordered = _applyTabOrder(sorted);
    let dragTab = null;
    for (const o of ordered) {
        const tab = document.createElement('button');
        tab.className = `orch-tab ${o.name === selectedAgent && o.scope === currentScope ? 'active' : ''}`;
        tab.dataset.orchName = o.name;
        tab.draggable = true;
        const dot = document.createElement('span');
        dot.className = 'tab-dot';
        dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : '#eab308';
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

function updateOrchTabDots() {
    const tabs = document.querySelectorAll('#orch-tabs .orch-tab');
    tabs.forEach(tab => {
        const scope = tab.title;
        const o = orchData.find(x => x.scope === scope);
        if (!o) return;
        const dot = tab.querySelector('.tab-dot');
        if (dot) dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : '#eab308';
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

    const recent = JSON.parse(localStorage.getItem('recentOrchs') || '[]');
    const filtered = recent.filter(n => n !== name);
    filtered.unshift(name);
    localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));

    onOrchestratorChange();
    renderOrchTabs(orchData);
}

function onOrchestratorChange() {
    saveDraft();
    const picker = $('#orch-picker');
    const opt = picker.selectedOptions[0];
    currentScope = picker.value || null;
    chatLogs = {};
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    streamBubble = null;
    streamContent = '';
    selectedAgent = opt?.dataset?.name || null;
    if (currentScope && selectedAgent) {
        localStorage.setItem('lastOrchScope', currentScope);
        localStorage.setItem('lastOrchName', selectedAgent);
    }
    $('#chat').innerHTML = '';
    scrollAfterLoad = true;
    updateAgentInfo(null);
    restoreDraft();
    refreshSessions(); connectSSE(); initFilePanel();
    if (_tasksTabActive) loadTasks();
}

// === Agent Selection ===
function selectAgent(name) {
    saveDraft();
    selectedAgent = name;
    streamBubble = null;
    streamContent = '';
    $('#chat').innerHTML = '';
    if (chatLogs[name]) chatLogs[name].lastId = 0;
    scrollAfterLoad = true;
    updateInputState();
    restoreDraft();
    renderAgentList();
    fetchAgentContext(name);
    refreshSessions(); connectSSE();
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

function updateAgentInfo(session) {
    if (!session) {
        $('#ai-name').textContent = '-';
        $('#ai-status').textContent = '';
        $('#ai-model').textContent = '-';
        $('#ai-cost').textContent = '-';
        $('#ai-branch').textContent = '-';
        $('#ai-scope').textContent = '-';
        setContextDisplay('-');
        $('#view-prompt-btn').classList.add('hidden');
        $('#compact-btn').classList.add('hidden');
        return;
    }
    $('#view-prompt-btn').classList.remove('hidden');
    $('#compact-btn').classList.remove('hidden');
    $('#ai-name').textContent = session.name;
    const st = $('#ai-status');
    st.textContent = `● ${session.status}`;
    st.className = `text-xs font-mono status-${session.status}`;
    $('#ai-model').textContent = session.model || '-';
    $('#ai-cost').textContent = `$${session.cost_usd || 0}`;
    $('#ai-branch').textContent = session.branch || '-';
    $('#ai-scope').textContent = session.scope || '-';
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
    if (ctx.cache_hit !== undefined) s += ` · cache ${ctx.cache_hit}%`;
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

    const active = sessions;
    const archive = [];

    for (const s of active) {
        if (s.color) agentColors[s.name] = s.color;
        list.appendChild(createAgentItem(s));
    }

    if (archive.length > 0) {
        const divider = document.createElement('div');
        divider.className = 'text-xs text-slate-700 uppercase tracking-wider px-3 pt-3 pb-1';
        divider.textContent = `Archive (${archive.length})`;
        list.appendChild(divider);
        for (const s of archive) {
            list.appendChild(createAgentItem(s));
        }
    }
}

function createAgentItem(s) {
    const isSelected = s.name === selectedAgent;
    const isDead = s.status === 'stopped' || s.status === 'error';
    const item = document.createElement('div');
    item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isSelected ? 'bg-indigo-900/30 border border-indigo-500/30' :
        isDead ? 'opacity-50 hover:opacity-70' : 'hover:bg-slate-800/50'
    }`;
    item.addEventListener('click', () => selectAgent(s.name));

    if (s.color) item.style.borderLeft = `3px solid ${s.color}`;

    const icon = document.createElement('span');
    icon.textContent = s.is_orchestrator ? '🎯' : isDead ? '🪦' : '⚙️';
    icon.className = 'text-sm';

    const info = document.createElement('div');
    info.className = 'flex-1 min-w-0';
    const nameRow = document.createElement('div');
    nameRow.className = 'flex items-center justify-between';
    const nameEl = document.createElement('span');
    nameEl.className = 'text-xs font-medium truncate';
    nameEl.textContent = s.name;
    const statusEl = document.createElement('span');
    const statusColor = s.status === 'running' ? '#22c55e' : s.status === 'idle' ? '#eab308' : '#6b7280';
    const statusBg = s.status === 'running' ? 'rgba(34,197,94,0.15)' : s.status === 'idle' ? 'rgba(234,179,8,0.12)' : 'rgba(107,114,128,0.1)';
    statusEl.className = 'text-xs font-mono font-bold shrink-0';
    statusEl.style.color = statusColor;
    statusEl.style.backgroundColor = statusBg;
    statusEl.style.padding = '1px 6px';
    statusEl.style.borderRadius = '4px';
    statusEl.textContent = `● ${s.status}`;
    nameRow.append(nameEl, statusEl);

    const meta = document.createElement('div');
    meta.className = 'text-xs text-slate-600 mt-0.5 flex justify-between';
    const modelSpan = document.createElement('span');
    modelSpan.textContent = s.model || '';
    meta.appendChild(modelSpan);
    if (s.cost_usd > 0) {
        const costSpan = document.createElement('span');
        costSpan.className = 'text-green-400';
        costSpan.textContent = `$${s.cost_usd.toFixed(2)}`;
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
    item.append(icon, info);

    if (isSelected) updateAgentInfo(s);
    return item;
}

// === Chat ===
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
        });
    } catch (e) {
        if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
        if (pendingBubble) { const ring = pendingBubble.querySelector('.debounce-ring'); if (ring) ring.remove(); }
        pendingBubble = null; pendingUserMsgs = [];
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

function finalizePending() {
    if (!pendingBubble) return;
    const ring = pendingBubble.querySelector('.debounce-ring');
    if (ring) ring.remove();
    const combined = pendingUserMsgs.join('\n');
    localMessages.add(combined);
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
        img.addEventListener('click', () => openFilePreview(path));
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
        navigator.clipboard.writeText(text);
        btn.textContent = '✅';
        setTimeout(() => btn.textContent = '📋', 1500);
    });
    el.appendChild(btn);
}

let streamBubble = null;
let streamContent = '';

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
            if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${({'claude-opus-4-6[1m]':'Opus 1M','claude-opus-4-6':'Opus','claude-sonnet-4-6':'Sonnet','claude-haiku-4-5':'Haiku','claude-haiku-4-6':'Haiku'})[parsed.model || 'claude-sonnet-4-6'] || parsed.model || 'Sonnet'})`;
            else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = `🌐 "${parsed.query || ''}"`;
            else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
            else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
            else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
            else if (rawName === 'mcp__orchestra__kill_worker') preview = `💀 Kill: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__stop_worker') preview = `⏸️ Stop: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__get_worker_logs') preview = `📋 Logs: ${parsed.name || '?'} (${parsed.limit || 20})`;
            else if (rawName === 'mcp__orchestra__list_agents') preview = '🎼 Agents';
            else if (rawName === 'mcp__orchestra__list_orchestrators') preview = '🎯 Orchestrators';
            else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__list_jobs') preview = '📊 Jobs';
            else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
            else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
            else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
            else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
            else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
            else if (rawName === 'mcp__orchestra__task_create') preview = `📋 New: "${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+'k' : ''}`;
            else if (rawName === 'mcp__orchestra__task_update') { const _f = Object.keys(parsed).filter(k=>k!=='par').map(k=>`${k}→${parsed[k]}`).join(', '); preview = `✏️ ${parsed.par || '?'}: ${_f}`; }
            else if (rawName === 'mcp__orchestra__task_list') { const _fl = [parsed.status,parsed.project,parsed.assignee].filter(Boolean).join(', '); preview = `📋 Tasks${_fl ? ' ('+_fl+')' : ''}`; }
            else if (rawName === 'mcp__orchestra__task_get') preview = `📋 ${parsed.par || '?'}`;
            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'}k ₽`;
            else if (rawName === 'mcp__orchestra__payment_status') preview = '💰 Balance';
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

function addChatEntry(type, content, ts, anchor) {
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');
    const _insert = (el) => anchor ? chat.insertBefore(el, anchor) : chat.appendChild(el);

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
        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
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
                const isOrchSimpleCompact = ['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__compact_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__merge_worker','mcp__orchestra__list_agents','mcp__orchestra__list_orchestrators','mcp__orchestra__list_jobs','mcp__orchestra__get_worker_logs'].includes(rawName);
                const isGlobCompact = rawName === 'Glob';
                const isSkillCompact = rawName === 'Skill';
                const isYougileCompact = rawName.startsWith('mcp__yougile__');
                const isWebFetchCompact = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
                const isWebSearchCompact = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan && isSendFileCompact) {
                    resultSpan.textContent = clean.includes('error') ? '❌' : '✅ sent';
                } else if (resultSpan && isOrchSimpleCompact) {
                    const hasErr = clean.includes('error') || clean.includes('Error');
                    if (['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__merge_worker'].includes(rawName)) resultSpan.textContent = hasErr ? '❌' : '✅';
                    else if (rawName === 'mcp__orchestra__compact_worker') { const m = clean.match(/(\d+)%/); resultSpan.textContent = m ? `✅ ${m[1]}%` : '✅'; }
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
        if (streamBubble) {
            streamBubble = null;
            streamContent = '';
        }
        const line = buildCompactToolLine(type, content, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(line);
        while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (type === 'stream') {
        removeWaitingIndicator();
        streamContent += content;
        if (!streamBubble) {
            streamBubble = document.createElement('div');
            streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body';
            streamBubble.style.position = 'relative';
            const agentColor = agentColors[selectedAgent];
            if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
            _insert(streamBubble);
        }
        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (type === 'text' && streamBubble) {
        addCopyBtn(streamBubble, streamContent);
        addTimestamp(streamBubble, ts);
        streamBubble = null;
        streamContent = '';
        return;
    }

    if (streamBubble && type !== 'text') {
        addCopyBtn(streamBubble, streamContent);
        addTimestamp(streamBubble, ts);
        streamBubble = null;
        streamContent = '';
    }

    if (type === 'status') {
        const badge = document.createElement('div');
        badge.className = 'text-center text-xs py-1 text-slate-500 italic';
        badge.textContent = `⚡ ${content}`;
        addTimestamp(badge, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(badge);
        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (type === 'subagent_start' || type === 'subagent_end' || type === 'subagent_progress') {
        const parts = content.split('|').map(p => p.trim());
        const desc = parts[0] || '';
        const meta = {};
        for (let i = 1; i < parts.length; i++) {
            const eq = parts[i].indexOf('=');
            if (eq > 0) meta[parts[i].slice(0, eq)] = parts[i].slice(eq + 1);
        }
        const el = document.createElement('div');
        el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';

        if (type === 'subagent_start') {
            el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
            el.innerHTML = `🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>`;
            if (meta.type) {
                const sub = document.createElement('div');
                sub.style.cssText = 'font-size:10px;color:#64748b;margin-top:1px;padding-left:20px';
                sub.textContent = `type: ${meta.type}`;
                el.appendChild(sub);
            }
        } else if (type === 'subagent_progress') {
            el.style.cssText += ';color:#64748b';
            const tokens = meta.tokens ? (parseInt(meta.tokens) >= 1000 ? (parseInt(meta.tokens) / 1000).toFixed(1) + 'k' : meta.tokens) : '';
            el.textContent = `⏳ "${desc}" — ${meta.tool ? 'using ' + meta.tool : ''}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
        } else {
            const ok = !meta.status || meta.status === 'completed';
            el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'completed' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
            const summaryStart = content.indexOf(meta.status || '') + (meta.status || '').length;
            const summaryText = parts.slice(2).join(' | ').replace(/^status=\w+\s*/, '').trim();
            if (summaryText) {
                const sumEl = document.createElement('div');
                sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;max-height:40px;overflow:hidden;white-space:pre-wrap';
                sumEl.textContent = summaryText.length > 200 ? summaryText.slice(0, 200) + '…' : summaryText;
                el.appendChild(sumEl);
                if (summaryText.length > 200) {
                    el.style.cursor = 'pointer';
                    let _saExp = false;
                    el.addEventListener('click', () => {
                        _saExp = !_saExp;
                        sumEl.textContent = _saExp ? summaryText : summaryText.slice(0, 200) + '…';
                        sumEl.style.maxHeight = _saExp ? 'none' : '40px';
                    });
                }
            }
        }
        addTimestamp(el, ts);
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        _insert(el);
        if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
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

        const isSendMsg = rawName === 'mcp__orchestra__send_message';
        if (isSendMsg) {
            try {
                const d = JSON.parse(body);
                const to = d.to || d.message?.substring(0, 30) || '?';
                const msg = d.message || '';
                header.textContent = `📨 → ${to}`;
                header.style.color = '#a78bfa';
                const previewText = msg.length > 200 ? msg.slice(0, 200) : msg;
                const hasMore = msg.length > 200;
                const previewEl = document.createElement('div');
                previewEl.className = 'text-xs opacity-80 markdown-body';
                previewEl.innerHTML = DOMPurify.sanitize(marked.parse(previewText));
                div.appendChild(previewEl);
                if (hasMore) {
                    const restEl = document.createElement('div');
                    restEl.className = 'text-xs opacity-80 markdown-body';
                    restEl.innerHTML = DOMPurify.sanitize(marked.parse(msg.slice(200)));
                    restEl.style.display = 'none';
                    restEl.dataset.role = 'send-rest';
                    div.appendChild(restEl);
                    const restLines = msg.slice(200).split('\n').length;
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.color = '#a78bfa';
                    hint.style.cursor = 'pointer';
                    hint.textContent = `▼ ${restLines} more lines`;
                    hint.dataset.role = 'send-hint';
                    div.appendChild(hint);
                    div.style.cursor = 'pointer';
                    let sendExpanded = false;
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        sendExpanded = !sendExpanded;
                        restEl.style.display = sendExpanded ? 'block' : 'none';
                        hint.textContent = sendExpanded ? '▲ collapse' : `▼ ${restLines} more lines`;
                    });
                }
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
                    'claude-opus-4-6[1m]': 'Opus 4.6 1M',
                    'claude-opus-4-6': 'Opus 4.6',
                    'claude-sonnet-4-6': 'Sonnet 4.6',
                    'claude-haiku-4-5': 'Haiku 4.5',
                    'claude-haiku-4-6': 'Haiku 4.6',
                };
                const MODEL_COLOR = {
                    'claude-opus-4-6[1m]': '#a78bfa',
                    'claude-opus-4-6': '#a78bfa',
                    'claude-sonnet-4-6': '#38bdf8',
                    'claude-haiku-4-5': '#4ade80',
                    'claude-haiku-4-6': '#4ade80',
                };
                if (model) {
                    const badge = document.createElement('span');
                    badge.textContent = MODEL_SHORT[model] || model;
                    badge.style.cssText = `font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:${MODEL_COLOR[model] || '#94a3b8'};border-color:${MODEL_COLOR[model] || '#94a3b8'};opacity:0.8;vertical-align:middle;margin-left:6px`;
                    header.appendChild(badge);
                }

                const PREVIEW = 200;
                const hasMoreTask = task.length > PREVIEW;
                const expandables = [];

                if (task) {
                    const taskEl = document.createElement('div');
                    taskEl.className = 'text-xs opacity-80 markdown-body';
                    taskEl.innerHTML = DOMPurify.sanitize(marked.parse(hasMoreTask ? task.slice(0, PREVIEW) : task));
                    div.appendChild(taskEl);
                    if (hasMoreTask) {
                        const restEl = document.createElement('div');
                        restEl.className = 'text-xs opacity-80 markdown-body';
                        restEl.innerHTML = DOMPurify.sanitize(marked.parse(task.slice(PREVIEW)));
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
            'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
            'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
            'mcp__orchestra__list_jobs': () => ({ icon: '📊', label: 'Jobs', color: '#38bdf8' }),
            'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price}k ₽` : '' }),
            'mcp__orchestra__task_update': (d) => { const f = Object.keys(d).filter(k=>k!=='par').map(k=>`${k}→${d[k]}`).join(', '); return { icon: '✏️', label: `${d.par||'?'}: ${f}`, color: '#38bdf8' }; },
            'mcp__orchestra__task_list': (d) => { const f = [d.status,d.project,d.assignee].filter(Boolean).join(', '); return { icon: '📋', label: `Tasks${f ? ' ('+f+')' : ''}`, color: '#a78bfa' }; },
            'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `Task ${d.par||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'}k ₽`, color: '#22c55e', sub: d.note || '' }),
            'mcp__orchestra__payment_status': () => ({ icon: '💰', label: 'Balance', color: '#eab308' }),
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
                    subEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px';
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
                const d = JSON.parse(body);
                const cmd = d.command || body;
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
        } else if (!isSendMsg && !isGrepTool && !isBashTool && !isAgentTool && !isSpawnWorker && !isWebSearchCall && !isToolSearchCall && !isBugReport && !isWebFetch && !isSendFile && !isOrchSimple && !isGlob && !isSkill && !isYougile) {
            const toolPreview = body.length > 200 ? body.slice(0, 200) + '…' : body;
            const toolFull = body.length > 200 ? body : null;
            if (body) {
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
                img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
                img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
                img.addEventListener('click', () => _showImageOverlay(img.src));
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
                if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            }
            return;
        }
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        const escaped = clean.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const linked = escaped.replace(/(https?:\/\/[^\s\])"&]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
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
                addTimestamp(lastTool, ts);
                return;
            }
            const _tmTools = ['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__task_list','mcp__orchestra__task_get','mcp__orchestra__payment_receive','mcp__orchestra__payment_status'];
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
                    if (hdr) { hdr.textContent = `📋 ${parsed.par}: ${parsed.title || '?'}`; hdr.style.color = '#22c55e'; }
                    const info = document.createElement('div');
                    info.style.cssText = 'margin-top:4px;display:flex;gap:8px;font-size:10px;color:#64748b;flex-wrap:wrap';
                    if (parsed.status) info.innerHTML += `<span>status: <b style="color:#e2e8f0">${parsed.status}</b></span>`;
                    if (parsed.price && parsed.price !== '0') info.innerHTML += `<span>price: <b style="color:#eab308">${parsed.price}k</b></span>`;
                    if (parsed.assignee) info.innerHTML += `<span>→ ${DOMPurify.sanitize(parsed.assignee)}</span>`;
                    lastTool.appendChild(info);
                    if (parsed.description) {
                        const descEl = document.createElement('div');
                        descEl.className = 'text-xs';
                        descEl.style.cssText = 'margin-top:4px;max-height:54px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;white-space:pre-wrap;color:#94a3b8';
                        descEl.textContent = parsed.description.slice(0, 200) + (parsed.description.length > 200 ? '…' : '');
                        lastTool.appendChild(descEl);
                        if (parsed.description.length > 200) {
                            lastTool.style.cursor = 'pointer';
                            let _tgExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _tgExp = !_tgExp;
                                descEl.textContent = _tgExp ? parsed.description : parsed.description.slice(0, 200) + '…';
                                descEl.style.maxHeight = _tgExp ? 'none' : '54px';
                            });
                        }
                    }
                } else if (tn === 'mcp__orchestra__task_update') {
                    if (hdr) { hdr.textContent = `✅ ${parsed.par || '?'} updated`; hdr.style.color = '#22c55e'; }
                    if (parsed.changes) {
                        const ch = document.createElement('div');
                        ch.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8';
                        ch.textContent = parsed.changes;
                        lastTool.appendChild(ch);
                    }
                } else if (tn === 'mcp__orchestra__task_list') {
                    const tasks = parsed.tasks || [];
                    if (hdr) hdr.textContent = `📋 ${tasks.length} tasks` + (parsed.total_debt && parsed.total_debt !== '0' ? ` | debt: ${parsed.total_debt}k` : '');
                    if (tasks.length > 0) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                        const PREVIEW = 4;
                        for (const [i, t] of tasks.entries()) {
                            const row = document.createElement('div');
                            row.style.cssText = `font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:6px;align-items:center${i >= PREVIEW ? ';display:none' : ''}`;
                            row.dataset.taskRow = '1';
                            const priceStr = t.price && t.price !== '0' ? `<span style="color:#eab308">${t.price}k</span>` : '';
                            row.innerHTML = `<span style="color:#64748b;font-family:monospace;min-width:32px">${t.par.replace('PAR-','')}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(t.title)}</span><span style="color:#64748b">${t.status}</span>${priceStr}`;
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
                    if (hdr) { hdr.textContent = `💰 +${parsed.amount || '?'}k received`; hdr.style.color = '#22c55e'; }
                    if (parsed.distributions && parsed.distributions.length > 0) {
                        const dEl = document.createElement('div');
                        dEl.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8';
                        dEl.textContent = parsed.distributions.map(d => `${d.par}: +${d.amount}k`).join(' | ');
                        lastTool.appendChild(dEl);
                    }
                } else if (tn === 'mcp__orchestra__payment_status') {
                    if (hdr) {
                        const bal = parsed.balance_display || '0';
                        const debt = parsed.total_debt_display || '0';
                        hdr.textContent = `💰 Balance: ${bal}k | Debt: ${debt}k`;
                        hdr.style.color = '#eab308';
                    }
                    if (parsed.recent_payments && parsed.recent_payments.length > 0) {
                        const pEl = document.createElement('div');
                        pEl.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                        pEl.innerHTML = parsed.recent_payments.slice(0, 3).map(p => `${p.date}: <span style="color:#22c55e">+${p.amount}</span>${p.note ? ' — '+DOMPurify.sanitize(p.note) : ''}`).join('<br>');
                        lastTool.appendChild(pEl);
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const _orchSimpleResults = {
                'mcp__orchestra__kill_worker': { ok: '💀 Worker killed', fail: '❌ Kill failed', okColor: '#22c55e', failColor: '#ef4444' },
                'mcp__orchestra__stop_worker': { ok: '⏸️ Worker stopped', fail: '❌ Stop failed', okColor: '#22c55e', failColor: '#ef4444' },
                'mcp__orchestra__compact_worker': null,
                'mcp__orchestra__rename_worker': { ok: '✅ Renamed', fail: '❌ Rename failed', okColor: '#22c55e', failColor: '#ef4444' },
                'mcp__orchestra__change_worker_model': { ok: '✅ Model changed', fail: '❌ Change failed', okColor: '#22c55e', failColor: '#ef4444' },
                'mcp__orchestra__merge_worker': { ok: '🔀 Merged', fail: '❌ Merge failed', okColor: '#22c55e', failColor: '#ef4444' },
                'mcp__orchestra__list_agents': null,
                'mcp__orchestra__list_orchestrators': null,
                'mcp__orchestra__list_jobs': null,
                'mcp__orchestra__get_worker_logs': null,
            };
            const _orchResultCfg = _orchSimpleResults[lastTool.dataset.toolRawName];
            if (_orchResultCfg !== undefined) {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (_orchResultCfg) {
                    const hasErr = content.includes('error') || content.includes('Error');
                    if (hdr) { hdr.textContent = hasErr ? _orchResultCfg.fail : _orchResultCfg.ok; hdr.style.color = hasErr ? _orchResultCfg.failColor : _orchResultCfg.okColor; }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__compact_worker') {
                    const pctMatch = clean.match(/(\d+)%\s*→\s*(\d+)%/) || clean.match(/(\d+)%.*?(\d+)%/);
                    if (hdr && pctMatch) { hdr.textContent = `✅ Compact: ${pctMatch[1]}% → ${pctMatch[2]}%`; hdr.style.color = '#22c55e'; }
                    else if (hdr) { hdr.textContent = '✅ Compacted'; hdr.style.color = '#22c55e'; }
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
                            const cost = parts[3] || '';
                            const ctxRaw = parts[4] || '';
                            const nameClean = nameRaw.replace(/\*\*/g, '').replace(/^[^\w]*/, '').trim();
                            const icon = nameRaw.match(/[🎯⚙️🔧]/)?.[0] || '⚙️';
                            const ctxPct = parseInt(ctxRaw.match(/(\d+)%/)?.[1] || '0');
                            const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                            const isRunning = status.includes('running');
                            const row = document.createElement('div');
                            row.style.cssText = `padding:4px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${isRunning ? '#22c55e' : '#334155'}`;
                            if (i >= PREVIEW_COUNT) row.style.display = 'none';
                            row.dataset.agentRow = '1';
                            row.innerHTML = `<div style="display:flex;align-items:center;justify-content:between;gap:6px"><span style="font-size:11px;color:#e2e8f0;font-weight:600">${icon} ${DOMPurify.sanitize(nameClean)}</span><span style="margin-left:auto;font-size:10px;color:${isRunning ? '#22c55e' : '#64748b'}">${DOMPurify.sanitize(status)}</span></div><div style="display:flex;align-items:center;gap:8px;margin-top:2px;font-size:10px;color:#64748b"><span>${DOMPurify.sanitize(model)}</span><span style="color:#22c55e">${DOMPurify.sanitize(cost)}</span><span style="display:inline-flex;align-items:center;gap:3px"><span style="display:inline-block;width:30px;height:3px;border-radius:2px;background:rgba(51,65,85,0.5);overflow:hidden"><span style="display:block;width:${Math.min(ctxPct,100)}%;height:100%;background:${ctxColor};border-radius:2px"></span></span><span style="color:${ctxColor}">${ctxPct}%</span></span></div>`;
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
                const files = clean.split('\n').filter(l => l.trim());
                const resultEl = document.createElement('div');
                resultEl.className = 'text-xs';
                resultEl.style.cssText = 'margin-top:6px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;white-space:pre-wrap;color:#94a3b8';
                resultEl.textContent = files.length ? files.join('\n') : '(no matches)';
                lastTool.appendChild(resultEl);
                if (files.length > 5) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = `▼ ${files.length - 5} more files`;
                    lastTool.appendChild(hint);
                    let _globExp = false;
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        _globExp = !_globExp;
                        resultEl.style.maxHeight = _globExp ? 'none' : '90px';
                        resultEl.style.overflowY = _globExp ? 'visible' : 'hidden';
                        hint.textContent = _globExp ? '▲ collapse' : `▼ ${files.length - 5} more files`;
                    });
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
                        img.addEventListener('click', () => openFilePreview(readPath));
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
            if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            return;
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
    else if (type === 'error') { div.textContent = content; }
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
    if (!anchor && wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

// === Grep Results Renderer ===
function renderGrepResults(raw, pattern) {
    const lines = raw.split('\n').filter(l => l.trim());
    if (!lines.length) return null;

    const PREVIEW = 5;

    // highlight pattern in escaped text
    function highlightPattern(text) {
        if (!pattern) return _escHtml(text);
        try {
            const escaped = _escHtml(text);
            const re = new RegExp(pattern, 'gi');
            return escaped.replace(re, s => `<span style="background:rgba(234,179,8,0.3);color:#fef08a;border-radius:2px">${s}</span>`);
        } catch { return _escHtml(text); }
    }

    // parse line: file:linenum:content OR linenum:content OR bare filename
    function parseLine(text) {
        // file:linenum:content  (file may contain path separators)
        const m = text.match(/^(.+?):(\d+):(.*)$/);
        if (m) return { file: m[1], line: m[2], content: m[3] };
        // linenum:content (files_with_matches w/ context)
        const m2 = text.match(/^(\d+):(.*)$/);
        if (m2) return { file: null, line: m2[1], content: m2[2] };
        // bare filename
        return { file: text, line: null, content: null };
    }

    function buildRow(text) {
        const p = parseLine(text);
        const row = document.createElement('div');
        row.className = 'grep-result-row';

        if (p.content !== null) {
            // match row: file:line on left, content on right
            const meta = document.createElement('span');
            meta.className = 'grep-meta';
            if (p.file) {
                const shortFile = p.file.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '');
                meta.textContent = `${shortFile}:${p.line}`;
                meta.title = `${p.file}:${p.line}`;
            } else {
                meta.textContent = p.line;
            }
            const code = document.createElement('span');
            code.className = 'grep-code';
            code.innerHTML = highlightPattern(p.content.trimStart());
            row.append(meta, code);
        } else {
            // bare filename (files_with_matches mode)
            const meta = document.createElement('span');
            meta.className = 'grep-meta';
            meta.textContent = '';
            const code = document.createElement('span');
            code.className = 'grep-code';
            code.style.color = '#38bdf8';
            const shortFile = p.file.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '');
            code.textContent = shortFile;
            row.append(meta, code);
        }
        return row;
    }

    const container = document.createElement('div');
    container.className = 'grep-results';
    container.style.marginTop = '6px';

    const previewLines = lines.slice(0, PREVIEW);
    const restLines = lines.slice(PREVIEW);

    for (const l of previewLines) container.appendChild(buildRow(l));

    if (restLines.length > 0) {
        const restEl = document.createElement('div');
        restEl.dataset.role = 'read-rest';
        restEl.style.display = 'none';
        for (const l of restLines) restEl.appendChild(buildRow(l));
        container.appendChild(restEl);

        const moreEl = document.createElement('div');
        moreEl.dataset.role = 'read-more';
        moreEl.dataset.count = restLines.length;
        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px;padding:4px 0';
        moreEl.textContent = `▼ ${restLines.length} more lines`;
        container.appendChild(moreEl);
    }

    return container;
}

// === WebSearch Results Renderer ===
function _wsCompactLinks(links) {
    const div = document.createElement('div');
    div.style.cssText = 'margin-top:6px;padding-top:6px;border-top:1px solid rgba(51,65,85,0.5)';
    for (const [i, r] of links.slice(0, 8).entries()) {
        const title = r.title || r.name || '';
        const url = r.url || r.link || r.href || '';
        if (!url) continue;
        let domain = '';
        try { domain = new URL(url).hostname.replace(/^www\./, ''); } catch {}
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.style.cssText = 'display:block;font-size:10px;margin-top:2px;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none';
        a.onmouseenter = () => a.style.color = '#94a3b8';
        a.onmouseleave = () => a.style.color = '#64748b';
        a.textContent = `[${i + 1}] ${title || domain}${title && domain ? ' — ' + domain : ''}`;
        div.appendChild(a);
    }
    return div.children.length > 0 ? div : null;
}

function _wsCollapsible(el) {
    const PREVIEW_LINES = 5;
    const PREVIEW_HEIGHT = PREVIEW_LINES * 18;
    const body = el.querySelector('.markdown-body');
    if (!body) return el;

    const wrapper = document.createElement('div');
    wrapper.className = 'websearch-results';
    while (el.firstChild) wrapper.appendChild(el.firstChild);

    body.style.cssText += ';max-height:' + PREVIEW_HEIGHT + 'px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word';

    const hint = document.createElement('div');
    hint.style.cssText = 'color:#38bdf8;font-size:10px;cursor:pointer;margin-top:4px';
    hint.textContent = '▼ expand';
    let expanded = false;

    const linksEl = wrapper.querySelector('[style*="border-top"]');

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

function renderWebSearchResults(raw) {
    let data;
    try { data = JSON.parse(raw); } catch { data = null; }

    if (data) {
        if (data.result && typeof data.result === 'string') {
            const el = document.createElement('div');
            const body = document.createElement('div');
            body.className = 'text-xs markdown-body';
            body.style.cssText = 'line-height:1.5;color:#cbd5e1';
            body.innerHTML = DOMPurify.sanitize(marked.parse(data.result));
            el.appendChild(body);
            if (Array.isArray(data.citations) && data.citations.length > 0) {
                const links = data.citations.map((url, i) => ({ title: '', url }));
                const linksEl = _wsCompactLinks(links);
                if (linksEl) el.appendChild(linksEl);
            }
            return _wsCollapsible(el);
        }
        const results = data.results || data.web?.results || data.organic_results || null;
        if (Array.isArray(results) && results.length > 0) {
            const el = document.createElement('div');
            const body = document.createElement('div');
            body.className = 'text-xs markdown-body';
            body.style.cssText = 'line-height:1.5;color:#cbd5e1';
            const md = results.slice(0, 6).map((r, i) => {
                const title = r.title || r.name || '';
                const url = r.url || r.link || r.href || '';
                const snippet = r.snippet || r.description || r.body || '';
                const link = url ? `[${title || url}](${url})` : (title || '');
                return `**${i + 1}.** ${link}${snippet ? '\n' + snippet : ''}`;
            }).join('\n\n');
            body.innerHTML = DOMPurify.sanitize(marked.parse(md));
            el.appendChild(body);
            return _wsCollapsible(el);
        }
    }

    const linksIdx = raw.indexOf('Links: [');
    if (linksIdx >= 0) {
        const arrStart = raw.indexOf('[', linksIdx);
        let depth = 0, arrEnd = -1;
        for (let i = arrStart; i < raw.length; i++) {
            if (raw[i] === '[') depth++;
            else if (raw[i] === ']') { depth--; if (depth === 0) { arrEnd = i + 1; break; } }
        }
        if (arrEnd > arrStart) try {
            const links = JSON.parse(raw.slice(arrStart, arrEnd));
            if (Array.isArray(links) && links.length > 0) {
                const el = document.createElement('div');
                const textAfterLinks = raw.slice(arrEnd).trim();
                const body = document.createElement('div');
                body.className = 'text-xs markdown-body';
                body.style.cssText = 'line-height:1.5;color:#cbd5e1';
                if (textAfterLinks) {
                    body.innerHTML = DOMPurify.sanitize(marked.parse(textAfterLinks));
                } else {
                    const md = links.slice(0, 8).map((r, i) => {
                        const title = r.title || r.name || '';
                        const url = r.url || r.link || '';
                        return `**${i + 1}.** [${title || url}](${url})`;
                    }).join('\n\n');
                    body.innerHTML = DOMPurify.sanitize(marked.parse(md));
                }
                el.appendChild(body);
                const linksEl = _wsCompactLinks(links);
                if (linksEl) el.appendChild(linksEl);
                return _wsCollapsible(el);
            }
        } catch {}
    }

    const metaMatch = raw.match(/^_(.*?\|.*?tokens.*?\|.*?\$[\d.]+)_\s*/m);
    if (metaMatch || raw.match(/^#{1,3}\s/m)) {
        const el = document.createElement('div');
        if (metaMatch) {
            const meta = document.createElement('div');
            meta.style.cssText = 'font-size:10px;color:#64748b;margin-bottom:4px';
            meta.textContent = metaMatch[1].replace(/^_|_$/g, '').trim();
            el.appendChild(meta);
        }
        const text = metaMatch ? raw.slice(raw.indexOf(metaMatch[0]) + metaMatch[0].length).trim() : raw;
        const body = document.createElement('div');
        body.className = 'text-xs markdown-body';
        body.style.cssText = 'line-height:1.5;color:#cbd5e1';
        body.innerHTML = DOMPurify.sanitize(marked.parse(text));
        el.appendChild(body);
        return _wsCollapsible(el);
    }

    return null;
}

// === Diff View ===
function _escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function _inlineDiff(oldLine, newLine) {
    const dmp = new diff_match_patch();
    const diffs = dmp.diff_main(oldLine, newLine);
    dmp.diff_cleanupSemantic(diffs);
    let common = 0, total = 0;
    for (const [op, text] of diffs) { total += text.length; if (op === 0) common += text.length; }
    if (total === 0 || common / total < 0.4) return null;
    let delHtml = '', addHtml = '';
    for (const [op, text] of diffs) {
        const esc = _escHtml(text);
        if (op === 0) { delHtml += esc; addHtml += esc; }
        else if (op === -1) delHtml += `<span style="background:rgba(239,68,68,0.35);border-radius:2px">${esc}</span>`;
        else addHtml += `<span style="background:rgba(34,197,94,0.35);border-radius:2px">${esc}</span>`;
    }
    return { delHtml, addHtml };
}

function buildDiffLines(oldStr, newStr) {
    const a = oldStr.split('\n'), b = newStr.split('\n');
    const n = a.length, m = b.length;
    const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
    for (let i = 1; i <= n; i++)
        for (let j = 1; j <= m; j++)
            dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
    const raw = [];
    let i = n, j = m;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && a[i-1] === b[j-1]) { raw.push({type:'ctx', text: a[i-1]}); i--; j--; }
        else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) { raw.push({type:'add', text: b[j-1]}); j--; }
        else { raw.push({type:'del', text: a[i-1]}); i--; }
    }
    raw.reverse();
    const result = [];
    let idx = 0;
    while (idx < raw.length) {
        if (raw[idx].type === 'del' && idx + 1 < raw.length && raw[idx+1].type === 'add') {
            const inline = _inlineDiff(raw[idx].text, raw[idx+1].text);
            if (inline) {
                result.push({type:'del', html: inline.delHtml});
                result.push({type:'add', html: inline.addHtml});
            } else {
                result.push({type:'del', html: _escHtml(raw[idx].text)});
                result.push({type:'add', html: _escHtml(raw[idx+1].text)});
            }
            idx += 2;
        } else {
            result.push({type: raw[idx].type, html: _escHtml(raw[idx].text)});
            idx++;
        }
    }
    return result;
}

function _buildDiffEl(lines) {
    const el = document.createElement('div');
    for (const line of lines) {
        const row = document.createElement('div');
        row.className = `diff-line diff-line-${line.type}`;
        const gutter = document.createElement('span');
        gutter.className = 'diff-gutter';
        gutter.textContent = line.type === 'del' ? '−' : line.type === 'add' ? '+' : ' ';
        const code = document.createElement('span');
        code.className = 'diff-code';
        code.innerHTML = line.html;
        row.append(gutter, code);
        el.appendChild(row);
    }
    return el;
}

function renderEditDiff(body) {
    let data;
    try { data = JSON.parse(body); } catch { return null; }
    const isWrite = data.content !== undefined && data.old_string === undefined;
    if (!isWrite && data.old_string === undefined && data.new_string === undefined) return null;

    const PREVIEW_LINES = 5;
    const lines = isWrite
        ? data.content.split('\n').map(l => ({type: 'add', html: _escHtml(l)}))
        : buildDiffLines(data.old_string || '', data.new_string || '');
    const fp = data.file_path || '';
    const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;

    const container = document.createElement('div');
    container.className = 'diff-view';

    const fileEl = document.createElement('div');
    fileEl.className = 'diff-file';
    fileEl.textContent = shortPath;
    fileEl.title = fp;
    container.appendChild(fileEl);

    const previewLines = lines.slice(0, PREVIEW_LINES);
    const restLines = lines.slice(PREVIEW_LINES);

    container.appendChild(_buildDiffEl(previewLines));

    if (restLines.length > 0) {
        const restEl = _buildDiffEl(restLines);
        restEl.style.display = 'none';
        container.appendChild(restEl);

        const moreEl = document.createElement('div');
        moreEl.className = 'diff-file';
        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
        moreEl.textContent = `▼ ${restLines.length} more lines`;
        moreEl.dataset.count = restLines.length;
        container.appendChild(moreEl);
    }

    return container;
}

function renderReadView(body) {
    let data;
    try { data = JSON.parse(body); } catch { return null; }
    if (!data.file_path) return null;

    const PREVIEW_LINES = 5;
    const fp = data.file_path || '';
    const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;
    const offset = data.offset || 0;
    const limit = data.limit || '';

    const container = document.createElement('div');
    container.className = 'diff-view';
    container.dataset.readPath = fp;

    const fileEl = document.createElement('div');
    fileEl.className = 'diff-file';
    fileEl.textContent = `${shortPath}${offset ? ` :${offset}` : ''}${limit ? ` (${limit} lines)` : ''}`;
    fileEl.title = fp;
    container.appendChild(fileEl);

    const skeleton = document.createElement('div');
    skeleton.className = 'read-skeleton';
    skeleton.dataset.role = 'read-skeleton';
    for (let i = 0; i < 3; i++) {
        const row = document.createElement('div');
        row.className = 'read-skeleton-line';
        skeleton.appendChild(row);
    }
    container.appendChild(skeleton);

    return container;
}

// === File Browser ===
const TOOL_ICONS = {
    'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️',
    'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
    'Agent': '🤖', 'Task': '🤖', 'TodoWrite': '📝', 'NotebookEdit': '📓',
    'ToolSearch': '🔍', 'AskUserQuestion': '❓', 'SendMessage': '💬',
};
const MCP_ICONS = {
    'orchestra': '🎼', 'websearch': '🌐', 'kesha': '🦜',
    'yougile': '📋', 'pandoc': '📄', 'aperant': '🏠',
    'github': '🐙', 'serena': '🧠', 'mailru': '📧',
};

function toolIcon(name) {
    if (name.startsWith('mcp__')) {
        const server = name.split('__')[1];
        return MCP_ICONS[server] || '🔌';
    }
    for (const [key, icon] of Object.entries(TOOL_ICONS)) {
        if (name === key || name.startsWith(key)) return icon;
    }
    return '🔧';
}

function toolShortName(name) {
    if (name.startsWith('mcp__')) {
        const parts = name.split('__');
        return parts.length >= 3 ? parts[2] : name;
    }
    return name;
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
        for (const f of files) {
            const item = document.createElement('div');
            item.className = `file-item ${f.is_dir ? 'file-dir' : 'file-file'}`;
            item.draggable = true;
            item.dataset.path = f.path;
            item.dataset.isDir = f.is_dir;
            item.textContent = `${getFileIcon(f.name, f.is_dir)} ${f.name}`;
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
                if (expanded) {
                    item.textContent = `📂 ${f.name}`;
                    loadFileTree(f.path, children);
                }
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
                container.appendChild(wrapper);
            } else {
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
                container.appendChild(item);
            }
        }
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

function initFilePanel() {
    const tree = $('#file-tree');

    const chatInput = $('#chat-input');
    if (!chatInput.dataset.fileDropReady) {
        chatInput.dataset.fileDropReady = '1';
        chatInput.addEventListener('dragover', (e) => { e.preventDefault(); chatInput.classList.add('border-indigo-400'); });
        chatInput.addEventListener('dragleave', () => chatInput.classList.remove('border-indigo-400'));
        chatInput.addEventListener('drop', (e) => {
            e.preventDefault();
            chatInput.classList.remove('border-indigo-400');
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
}

// === Refresh Loop ===
let refreshInProgress = false;
async function refreshSessions() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    if (refreshController) refreshController.abort();
    refreshController = new AbortController();
    const signal = refreshController.signal;
    const capturedScope = currentScope;

    try {
        if (!capturedScope) return;

        const [sessions, stats] = await Promise.all([
            api(`/api/sessions?scope=${encodeURIComponent(capturedScope)}`, { signal }),
            api(`/api/stats?scope=${encodeURIComponent(capturedScope)}`, { signal }),
        ]);

        if (capturedScope !== currentScope) return;
        _onServerOk();

        $('#stats-line').textContent = `${stats.active} active · ${stats.total_sessions} total · $${stats.total_cost_usd}`;
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
async function api(url, opts = {}) {
    const timeout = AbortSignal.timeout(5000);
    const signals = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
    const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts, signal: signals });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
}

// === Usage Bar ===
let _usageData = null;
let _usageError = false;
let _usageCountdownInterval = null;

function _usageColor(usagePct, resetPct) {
    if (resetPct == null) {
        if (usagePct >= 80) return '#ef4444';
        if (usagePct >= 50) return '#eab308';
        return '#22c55e';
    }
    const diff = usagePct - resetPct;
    if (diff < -10) return '#22c55e';
    if (diff > 10) return '#ef4444';
    const hue = Math.max(0, Math.min(120, 60 - diff * 6));
    return `hsl(${hue}, 80%, 50%)`;
}

function _resetPctNum(isoStr, windowMs) {
    if (!isoStr) return null;
    const remaining = new Date(isoStr) - Date.now();
    const elapsed = windowMs - remaining;
    return Math.max(0, Math.min(100, Math.round(elapsed / windowMs * 100)));
}

function _miniBar(pct, color) {
    return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span></span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
}

function renderUsageBar() {
    const bar = document.getElementById('usage-bar');
    if (!bar) return;
    if (!_usageData) {
        bar.innerHTML = '';
        bar.style.display = 'none';
        return;
    }
    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap';

    const a = _usageData.anthropic || {};
    const o = _usageData.orchestra || {};
    const parts = [];

    if (_usageError) parts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');

    const fh = a.five_hour;
    if (fh) {
        const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
        const c = _usageColor(fh.utilization, rpNum);
        const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c)}${rp}</span>`);
    }
    const sd = a.seven_day;
    if (sd) {
        const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
        const c = _usageColor(sd.utilization, rpNum);
        const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}</span>`);
    }

    parts.push('<span style="flex:1"></span>');

    if (typeof o.total_cost_usd === 'number') {
        parts.push(`<span style="color:#22c55e">$${o.total_cost_usd.toFixed(2)}</span>`);
    }
    if (typeof o.agents_count === 'number') {
        parts.push(`<span style="color:#64748b">${o.agents_count} agents</span>`);
    }

    bar.innerHTML = parts.join('');
}

async function fetchUsage() {
    try {
        _usageData = await api('/api/usage');
        _usageError = false;
    } catch {
        _usageError = true;
    }
    renderUsageBar();
}

function initUsageBar() {
    fetchUsage();
    setInterval(fetchUsage, 120000);
    _usageCountdownInterval = setInterval(() => {
        if (_usageData) renderUsageBar();
    }, 60000);
}

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

function _onServerError() {
    _rebootFails++;
    if (_rebootFails >= 2) _showRebootOverlay();
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
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

let _tasksTabActive = false;
let _tasksInterval = null;

function switchLeftTab(tab) {
    const fileTree = document.getElementById('file-tree');
    const tasksPanel = document.getElementById('tasks-panel');
    if (!fileTree || !tasksPanel) return;
    document.querySelectorAll('.left-tab').forEach(btn => {
        const isActive = btn.dataset.leftTab === tab;
        btn.classList.toggle('text-white', isActive);
        btn.classList.toggle('border-indigo-500', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
        btn.classList.toggle('border-transparent', !isActive);
    });
    if (tab === 'files') {
        fileTree.classList.remove('hidden');
        tasksPanel.classList.add('hidden');
        _tasksTabActive = false;
        if (_tasksInterval) { clearInterval(_tasksInterval); _tasksInterval = null; }
    } else {
        fileTree.classList.add('hidden');
        tasksPanel.classList.remove('hidden');
        _tasksTabActive = true;
        loadTasks();
        if (!_tasksInterval) _tasksInterval = setInterval(loadTasks, 30000);
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
const COLLAPSED_DEFAULT = new Set(['backlog', 'paid', 'cancelled']);
let _taskCollapsed = {};

async function loadTasks() {
    const panel = document.getElementById('tasks-panel');
    if (!panel) return;
    try {
        const scope = currentScope || '';
        const [tasksResp, payResp, syncResp] = await Promise.all([
            fetch(`/api/tm/tasks?scope=${encodeURIComponent(scope)}`),
            fetch('/api/tm/payments/status').catch(() => null),
            fetch('/api/tm/sync/log?limit=10').catch(() => null),
        ]);
        const data = await tasksResp.json();
        const payData = payResp ? await payResp.json().catch(() => null) : null;
        const syncData = syncResp ? await syncResp.json().catch(() => null) : null;
        const pendingSyncs = (syncData?.entries || []).filter(e => e.status === 'error' || e.status === 'pending').length;
        renderTasksPanel(panel, data, payData, pendingSyncs);
    } catch (e) {
        panel.innerHTML = '<div class="p-2 text-slate-500">Failed to load tasks</div>';
    }
}

function renderTasksPanel(panel, data, payData, pendingSyncs) {
    const tasks = data.tasks || [];
    const grouped = {};
    for (const t of tasks) { (grouped[t.status] ||= []).push(t); }

    let html = '';
    html += '<div class="px-2 py-1.5 border-b border-slate-800/50 space-y-0.5">';
    if (payData && payData.balance_display) {
        html += `<div class="flex justify-between"><span class="text-slate-500">💰 Balance:</span><span class="text-emerald-400 font-mono">${escHtml(payData.balance_display)} ₽</span></div>`;
    }
    html += `<div class="flex justify-between"><span class="text-slate-500">📊 Debt:</span><span class="text-amber-400 font-mono">${escHtml(data.total_debt || '0')} ₽</span></div>`;
    if (pendingSyncs > 0) {
        html += `<div class="flex justify-between"><span class="text-slate-500">⚠️ Sync:</span><span class="text-red-400 font-mono">${pendingSyncs} pending</span></div>`;
    }
    html += '</div>';

    if (tasks.length === 0) {
        html += '<div class="p-4 text-center text-slate-600 italic">No tasks yet</div>';
        panel.innerHTML = html;
        return;
    }

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
            if (debt > 0) suffix = ` → ${debt}k ₽`;
        }
        html += '<div class="mt-1">';
        html += `<div class="px-2 py-1 flex items-center gap-1.5 cursor-pointer hover:bg-slate-800/30 rounded select-none" onclick="toggleTaskGroup('${status}')">`;
        html += `<span class="text-[10px]">${arrow}</span>`;
        html += `<span class="w-1.5 h-1.5 rounded-full ${dot} shrink-0"></span>`;
        html += `<span class="text-slate-400 font-bold flex-1">${label} (${group.length})</span>`;
        if (suffix) html += `<span class="text-amber-400 text-[10px] font-mono">${suffix}</span>`;
        html += '</div>';
        if (!isCollapsed) {
            for (const t of group) {
                const par = t.par.replace('PAR-', '');
                const priceInfo = t.price !== '0' ? (t.paid !== '0' ? `${t.paid}/${t.price}` : t.price) : '';
                html += `<div class="task-item flex items-center gap-1.5 px-2 py-0.5 hover:bg-slate-800/50 rounded cursor-pointer" style="position:relative" data-par="${par}" onclick="showTaskDetail('${par}')">`;
                html += `<span class="text-slate-600 font-mono shrink-0 w-6 text-right">${par}</span>`;
                html += `<span class="truncate flex-1 ${t.status === 'paid' ? 'text-slate-500' : ''}">${escHtml(t.title)}</span>`;
                if (priceInfo) html += `<span class="text-amber-400/70 shrink-0 font-mono">${priceInfo}</span>`;
                html += `<span class="task-inject-btn" onclick="event.stopPropagation();injectTask('${par}')" title="Insert PAR-${par} into chat">📩</span>`;
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
    const ref = `[PAR-${par}]`;
    if (!input.value.includes(`PAR-${par}`)) {
        input.value = (input.value ? input.value + ' ' : '') + ref;
        input.focus();
    }
}

async function showTaskDetail(par) {
    try {
        const r = await fetch(`/api/tm/tasks/${par}`);
        const t = await r.json();
        if (t.error) return;
        const modal = document.getElementById('prompt-modal');
        const nameEl = document.getElementById('prompt-modal-name');
        const bodyEl = document.getElementById('prompt-modal-body');
        if (!modal || !nameEl || !bodyEl) return;
        nameEl.textContent = t.par + ' ' + t.title;
        let html = '<div class="space-y-3">';
        html += '<div class="grid grid-cols-2 gap-2 text-xs">';
        html += `<div><span class="text-slate-500">Status:</span> <span class="font-bold">${t.status}</span></div>`;
        html += `<div><span class="text-slate-500">Price:</span> <span class="text-amber-400">${t.price_rub > 0 ? (t.price_rub/1000)+'k ₽' : '—'}</span></div>`;
        html += `<div><span class="text-slate-500">Paid:</span> ${t.paid_rub/1000}/${t.price_rub/1000}k</div>`;
        html += `<div><span class="text-slate-500">Debt:</span> <span class="text-red-400">${t.debt_rub > 0 ? (t.debt_rub/1000)+'k ₽' : '0'}</span></div>`;
        html += `<div><span class="text-slate-500">Assignee:</span> ${escHtml(t.assignee || '—')}</div>`;
        html += `<div><span class="text-slate-500">Project:</span> ${escHtml(t.project)}</div>`;
        html += `<div><span class="text-slate-500">Created:</span> ${(t.created_at||'').slice(0,10)}</div>`;
        if (t.completed_at) html += `<div><span class="text-slate-500">Done:</span> ${t.completed_at.slice(0,10)}</div>`;
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
        if (t.commits && t.commits.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">COMMITS</div>';
            for (const c of t.commits) { html += `<div class="text-xs font-mono">${c.slice(0,7)}</div>`; }
            html += '</div>';
        }
        html += '</div>';
        bodyEl.innerHTML = html;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    } catch (e) { console.error('Task detail error:', e); }
}
