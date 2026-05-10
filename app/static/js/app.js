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
            if (chatLogs[selectedAgent]) chatLogs[selectedAgent].lastId = 0;
            scrollAfterLoad = true;
            connectSSE();
        });
    }
    loadModels();
    loadOrchestrators();
    scheduleRefresh();
    initFilePreviewModal();
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
    const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}`;
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
        const anchor = chat.firstChild;
        for (const l of logs) {
            const tempDiv = document.createElement('div');
            // рендерим через addChatEntry — вставляем в начало, не в конец
            // используем флаг prepend mode
            _prependEntry(l.type, l.content, l.ts, chat, anchor);
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

// Prepend helper — строит bubble и вставляет перед anchor
function _prependEntry(type, content, ts, chat, anchor) {
    // Для простоты: создаём div, наполняем минимальным рендером
    const div = document.createElement('div');
    div.className = `px-3 py-2 rounded-lg text-sm break-words ${
        type === 'user_message' ? 'chat-user ml-16' :
        type === 'tool' ? 'chat-tool' :
        type === 'tool_result' ? 'chat-tool-result' :
        type === 'status' ? 'text-center text-xs py-1 text-slate-500 italic' :
        type === 'error' ? 'text-red-400 text-xs' :
        'chat-bot markdown-body'
    }`;
    if (type === 'status') {
        div.textContent = `⚡ ${content}`;
    } else if (type === 'error') {
        div.textContent = content;
    } else if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30);
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        const isOrch = rawName.startsWith('mcp__orchestra__');
        const hdr = document.createElement('div');
        hdr.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
        hdr.style.color = isOrch ? '#a78bfa' : '#38bdf8';
        hdr.textContent = `${toolIcon(rawName)} ${toolShortName(rawName)}`;
        div.appendChild(hdr);
        const bodyEl = document.createElement('div');
        bodyEl.style.whiteSpace = 'pre-wrap';
        bodyEl.className = 'text-xs opacity-70';
        bodyEl.textContent = body.length > 200 ? body.slice(0, 200) + '…' : body;
        div.appendChild(bodyEl);
    } else if (type === 'tool_result') {
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        div.style.whiteSpace = 'pre-wrap';
        div.textContent = '📎 ' + (clean.length > 200 ? clean.slice(0, 200) + '…' : clean);
    } else {
        div.innerHTML = DOMPurify.sanitize(marked.parse(content));
    }
    addTimestamp(div, ts);
    chat.insertBefore(div, anchor);
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
            contentEl.style.whiteSpace = 'pre-wrap';
            contentEl.style.overflowX = 'hidden';
            contentEl.style.wordWrap = 'break-word';
            contentEl.innerHTML = DOMPurify.sanitize(marked.parse(data.content));
        } else {
            contentEl.className = 'flex-1 overflow-auto text-xs p-4 text-slate-300';
            contentEl.style.whiteSpace = 'pre';
            contentEl.style.overflowX = 'auto';
            contentEl.style.wordWrap = 'normal';
            contentEl.textContent = data.content;
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

function renderOrchTabs(sorted) {
    const tabs = $('#orch-tabs');
    tabs.innerHTML = '';
    for (const o of sorted) {
        const tab = document.createElement('button');
        tab.className = `orch-tab ${o.name === selectedAgent && o.scope === currentScope ? 'active' : ''}`;
        const dot = document.createElement('span');
        dot.className = 'tab-dot';
        dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : '#eab308';
        const label = document.createElement('span');
        const shortName = o.name.replace(/-orchestrator$/, '');
        label.textContent = shortName;
        tab.append(dot, label);
        tab.title = o.scope;
        tab.addEventListener('click', () => selectOrchestrator(o.name, o.scope));
        tabs.appendChild(tab);
    }
}

function updateOrchTabDots() {
    const dots = document.querySelectorAll('#orch-tabs .orch-tab');
    dots.forEach(tab => {
        const name = tab.title;
        const o = orchData.find(x => x.scope === name);
        if (!o) return;
        const dot = tab.querySelector('.tab-dot');
        if (dot) dot.style.backgroundColor = (o.status === 'running' || o.any_running) ? '#22c55e' : '#eab308';
    });
}

function selectOrchestrator(name, scope) {
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
        return;
    }
    $('#view-prompt-btn').classList.remove('hidden');
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
                showImagePreview(data.url);
            }
        } catch (err) {
            input.value = oldText;
        }
        input.focus();
        break;
    }
}

function showImagePreview(url) {
    let container = $('#paste-preview');
    if (!container) {
        container = document.createElement('div');
        container.id = 'paste-preview';
        container.className = 'flex gap-2 px-3 py-1';
        $('#chat-input').parentElement.insertBefore(container, $('#chat-input'));
    }
    const wrap = document.createElement('div');
    wrap.className = 'relative';
    const img = document.createElement('img');
    img.src = url;
    img.className = 'h-16 rounded border border-slate-700';
    const rm = document.createElement('button');
    rm.className = 'absolute -top-1 -right-1 bg-red-600 text-white rounded-full w-4 h-4 text-xs leading-none';
    rm.textContent = '×';
    rm.addEventListener('click', () => {
        wrap.remove();
        pastedImages = pastedImages.filter(u => u !== url);
        if (!container.children.length) container.remove();
    });
    wrap.append(img, rm);
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
            if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
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

        const previewSpan = document.createElement('span');
        previewSpan.className = 'truncate flex-1 opacity-60';
        previewSpan.textContent = preview;

        const resultSpan = document.createElement('span');
        resultSpan.className = 'compact-result shrink-0';
        resultSpan.style.color = '#475569';

        line.append(iconSpan, nameSpan, previewSpan, resultSpan);
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
            const inner = document.createElement('div');
            inner.className = 'px-3 py-2 rounded-lg text-sm break-words chat-tool';
            const tempContent = line.dataset.toolContent;
            const tempResult = line.dataset.resultContent || '';
            const fakeDiv = { appendChild: (el) => inner.appendChild(el), dataset: {}, style: {}, querySelector: () => null };
            const ci = tempContent.indexOf(':');
            const rn = ci > 0 ? tempContent.slice(0, ci).trim() : tempContent.slice(0, 30);
            const bd = ci > 0 ? tempContent.slice(ci + 1).trim() : '';
            const fi = toolIcon(rn), sn = toolShortName(rn);
            const isO = rn.startsWith('mcp__orchestra__');
            const hdr = document.createElement('div');
            hdr.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
            hdr.style.color = isO ? '#a78bfa' : '#38bdf8';
            hdr.textContent = `${fi} ${sn}`;
            inner.appendChild(hdr);
            const isEditTool = rn === 'Edit' || rn === 'MultiEdit' || rn === 'Write';
            const isReadTool = rn === 'Read';
            const diffEl = isEditTool ? renderEditDiff(bd) : null;
            const readEl = isReadTool ? renderReadView(bd) : null;
            if (readEl) inner.appendChild(readEl);
            else if (diffEl) inner.appendChild(diffEl);
            else if (bd) {
                const bEl = document.createElement('div');
                bEl.style.whiteSpace = 'pre-wrap';
                bEl.className = 'text-xs opacity-70';
                bEl.textContent = bd.length > 200 ? bd.slice(0, 200) + '…' : bd;
                inner.appendChild(bEl);
            }
            if (tempResult) {
                const sep = document.createElement('div');
                sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                const rEl = document.createElement('div');
                rEl.className = 'text-xs';
                rEl.style.whiteSpace = 'pre-wrap';
                rEl.textContent = '📎 ' + (tempResult.length > 200 ? tempResult.slice(0, 200) + '…' : tempResult);
                sep.appendChild(rEl);
                inner.appendChild(sep);
            }
            fullBubble.appendChild(inner);
            line.after(fullBubble);
        });
    } else {
        line.textContent = '📎 ' + content.slice(0, 100);
    }

    return line;
}

function addChatEntry(type, content, ts) {
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');

    if (window.compactMode && (type === 'tool' || type === 'tool_result')) {
        if (type === 'tool_result') {
            const allCompact = chat.querySelectorAll('[data-compact-tool]');
            const lastC = allCompact.length ? allCompact[allCompact.length - 1] : null;
            if (lastC) {
                const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
                const rawName = lastC.dataset.toolRaw || '';
                const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
                const isReadTool = rawName === 'Read';
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan && !isEditTool && !isReadTool) {
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
        chat.appendChild(line);
        while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
        if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
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
            chat.appendChild(streamBubble);
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
        const chat = $('#chat');
        const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
        chat.appendChild(badge);
        if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
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
        header.textContent = `${icon} ${short}`;
        div.appendChild(header);

        const isSendMsg = rawName === 'mcp__orchestra__send_message' || rawName === 'mcp__orchestra__notify_kesha';
        if (isSendMsg) {
            try {
                const d = JSON.parse(body);
                const to = d.to || d.message?.substring(0, 30) || '?';
                const msg = d.message || '';
                header.textContent = `📨 → ${to}`;
                header.style.color = '#a78bfa';
                const msgEl = document.createElement('div');
                msgEl.className = 'text-xs opacity-80 markdown-body';
                msgEl.innerHTML = DOMPurify.sanitize(marked.parse(msg.length > 300 ? msg.slice(0, 300) + '…' : msg));
                div.appendChild(msgEl);
                div.dataset.isEdit = '1';
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
        } else if (!isSendMsg) {
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
        const lastTool = chat.querySelector('[data-last-tool]');
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        const escaped = clean.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const linked = escaped.replace(/(https?:\/\/[^\s\])"&]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const preview = linked.length > 200 ? linked.slice(0, 200) + '…' : linked;
        const full = linked.length > 200 ? linked : null;

        if (lastTool) {
            delete lastTool.dataset.lastTool;
            if (lastTool.dataset.isEdit) {
                addTimestamp(lastTool, ts);
                return;
            }
            const isWebSearch = lastTool.dataset.toolRawName === 'mcp__websearch__search' ||
                                lastTool.dataset.toolRawName === 'mcp__websearch__search_web';
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
            if (lastTool.dataset.isRead) {
                delete lastTool.dataset.lastTool;
                const readContainer = lastTool.querySelector('.diff-view');
                if (readContainer) {
                    const skeletonEl = readContainer.querySelector('[data-role="read-skeleton"]');
                    if (skeletonEl) skeletonEl.remove();
                    const readPath = readContainer.dataset.readPath || '';
                    if (/\.md$/i.test(readPath)) {
                        const PREVIEW_CHARS = 500;
                        const previewMd = clean.length > PREVIEW_CHARS ? clean.slice(0, PREVIEW_CHARS) : clean;
                        const previewEl = document.createElement('div');
                        previewEl.className = 'markdown-body';
                        previewEl.style.cssText = 'padding:6px 8px;font-size:11px';
                        previewEl.innerHTML = DOMPurify.sanitize(marked.parse(previewMd));
                        readContainer.appendChild(previewEl);
                        if (clean.length > PREVIEW_CHARS) {
                            const restMd = clean.slice(PREVIEW_CHARS);
                            const restEl = document.createElement('div');
                            restEl.className = 'markdown-body';
                            restEl.style.cssText = 'padding:0 8px 6px;font-size:11px';
                            restEl.dataset.role = 'read-rest';
                            restEl.style.display = 'none';
                            restEl.innerHTML = DOMPurify.sanitize(marked.parse(restMd));
                            readContainer.appendChild(restEl);
                            const moreEl = document.createElement('div');
                            moreEl.className = 'diff-file';
                            moreEl.dataset.role = 'read-more';
                            moreEl.dataset.count = restMd.length;
                            moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                            moreEl.textContent = `▼ more`;
                            readContainer.appendChild(moreEl);
                        }
                        addTimestamp(lastTool, ts);
                        return;
                    }
                    if (/\.(png|jpg|jpeg|gif|webp|svg)$/i.test(readPath)) {
                        const img = document.createElement('img');
                        img.src = `/api/files/raw?path=${encodeURIComponent(readPath)}`;
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

            const sep = document.createElement('div');
            sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs result-body';
            resultEl.style.whiteSpace = 'pre-wrap';
            resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
            resultEl.dataset.preview = preview;
            sep.appendChild(resultEl);
            if (full) {
                resultEl.dataset.full = full;
                const rHint = document.createElement('div');
                rHint.className = 'text-xs mt-1';
                rHint.style.color = '#38bdf8';
                rHint.textContent = `▼ ${clean.split('\n').length - preview.split('\n').length} more lines`;
                rHint.dataset.role = 'expand-hint';
                sep.appendChild(rHint);
            }
            lastTool.appendChild(sep);
            addTimestamp(lastTool, ts);
            return;
        }

        div.style.whiteSpace = 'pre-wrap';
        div.style.cursor = 'pointer';
        div.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
        if (full) {
            const sHint = document.createElement('div');
            sHint.className = 'text-xs mt-1';
            sHint.style.color = '#38bdf8';
            sHint.textContent = `▼ ${clean.split('\n').length - preview.split('\n').length} more lines`;
            div.appendChild(sHint);
        }
        let expanded = false;
        if (full) {
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'A') return;
                expanded = !expanded;
                div.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? full : preview, {ADD_ATTR: ['target']});
                if (!expanded) {
                    const h = document.createElement('div');
                    h.className = 'text-xs mt-1';
                    h.style.color = '#38bdf8';
                    h.textContent = `▼ ${clean.split('\n').length - preview.split('\n').length} more lines`;
                    div.appendChild(h);
                }
            });
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
    chat.appendChild(div);
    while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

// === WebSearch Results Renderer ===
function renderWebSearchResults(raw) {
    let data;
    try { data = JSON.parse(raw); } catch { return null; }
    const results = data.results || data.web?.results || data.organic_results || null;
    if (!Array.isArray(results) || results.length === 0) return null;

    const el = document.createElement('div');
    el.className = 'websearch-results';
    for (const r of results.slice(0, 6)) {
        const title = r.title || r.name || '';
        const url = r.url || r.link || r.href || '';
        const snippet = r.snippet || r.description || r.body || '';
        if (!title && !snippet) continue;
        const item = document.createElement('div');
        item.className = 'websearch-item';
        if (title && url) {
            const a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.className = 'websearch-title';
            a.textContent = title;
            item.appendChild(a);
        } else if (title) {
            const t = document.createElement('div');
            t.className = 'websearch-title';
            t.textContent = title;
            item.appendChild(t);
        }
        if (snippet) {
            const s = document.createElement('div');
            s.className = 'websearch-snippet';
            s.textContent = snippet.length > 160 ? snippet.slice(0, 160) + '…' : snippet;
            item.appendChild(s);
        }
        el.appendChild(item);
    }
    return el.children.length > 0 ? el : null;
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
                let expanded = false;
                const children = document.createElement('div');
                children.className = 'file-children hidden';
                item.addEventListener('click', async () => {
                    expanded = !expanded;
                    if (expanded && children.children.length === 0) {
                        await loadFileTree(f.path, children);
                    }
                    children.classList.toggle('hidden', !expanded);
                    item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
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

        $('#stats-line').textContent = `${stats.active} active · ${stats.total_sessions} total · $${stats.total_cost_usd}`;
        renderAgentList(sessions);

        try {
            const freshOrchs = await api('/api/orchestrators', { signal });
            for (const fo of freshOrchs) {
                const existing = orchData.find(o => o.name === fo.name);
                if (existing) { existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running; }
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
        if (e.name !== 'AbortError') console.warn('refresh error:', e);
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
