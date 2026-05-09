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

const $ = (s) => document.querySelector(s);

function saveDraft() {
    if (selectedAgent) drafts[selectedAgent] = $('#chat-input').value;
}
function restoreDraft() {
    $('#chat-input').value = drafts[selectedAgent] || '';
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
    loadModels();
    loadOrchestrators();
    scheduleRefresh();
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
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0 };
            if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
        } catch (e) { console.warn('SSE parse:', e); }
    };
    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        setTimeout(connectSSE, 2000);
    };
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
            item.innerHTML = `<span class="text-white font-medium">${p.name}</span> <span class="text-slate-500 text-xs">${p.path}</span>`;
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
    if (!confirm('Restart Orchestra server?')) return;
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
        return;
    }
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
    statusEl.className = 'text-xs font-mono font-bold';
    statusEl.style.color = statusColor;
    statusEl.style.textShadow = `0 0 6px ${statusColor}40`;
    statusEl.textContent = `● ${s.status}`;
    nameRow.append(nameEl, statusEl);

    const meta = document.createElement('div');
    meta.className = 'text-xs text-slate-600 mt-0.5';
    meta.textContent = s.model || '';

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
        meta.appendChild(bar);
    }

    info.append(nameRow, meta);
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
        const url = path.startsWith('/data/uploads/') ? '/uploads/' + path.split('/').pop() : null;
        if (!url) continue;
        const img = document.createElement('img');
        img.src = url;
        img.className = 'max-h-48 rounded mt-2';
        img.onerror = () => img.remove();
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

function addChatEntry(type, content, ts) {
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');

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
            body.textContent = msg;
            div.appendChild(body);
        } else {
            div.textContent = content;
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
        const header = document.createElement('div');
        header.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
        header.style.color = isOrch ? '#a78bfa' : '#38bdf8';
        header.textContent = `${icon} ${short}`;
        div.appendChild(header);

        if (body) {
            const preview = body.length > 200 ? body.slice(0, 200) + '…' : body;
            const full = body.length > 200 ? body : null;
            const bodyEl = document.createElement('div');
            bodyEl.style.whiteSpace = 'pre-wrap';
            bodyEl.className = 'text-xs opacity-70';
            bodyEl.textContent = preview;
            div.appendChild(bodyEl);
            if (full) {
                div.style.cursor = 'pointer';
                let expanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return;
                    expanded = !expanded;
                    bodyEl.textContent = expanded ? full : preview;
                });
            }
        }
    }
    else if (type === 'tool_result') {
        const chat = $('#chat');
        const lastTool = chat.querySelector('[data-last-tool]');
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        const linked = clean.replace(/(https?:\/\/[^\s\])"<>]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const preview = linked.length > 200 ? linked.slice(0, 200) + '…' : linked;
        const full = linked.length > 200 ? linked : null;

        if (lastTool) {
            delete lastTool.dataset.lastTool;
            const sep = document.createElement('div');
            sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs';
            resultEl.style.whiteSpace = 'pre-wrap';
            resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
            if (full) {
                resultEl.style.cursor = 'pointer';
                let expanded = false;
                resultEl.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    expanded = !expanded;
                    resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? full : preview, {ADD_ATTR: ['target']});
                });
            }
            sep.appendChild(resultEl);
            lastTool.appendChild(sep);
            addTimestamp(lastTool, ts);
            return;
        }

        div.style.whiteSpace = 'pre-wrap';
        div.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
        if (full) {
            div.style.cursor = 'pointer';
            let expanded = false;
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'A') return;
                expanded = !expanded;
                div.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? full : preview, {ADD_ATTR: ['target']});
            });
        }
    }
    else if (type === 'error') { div.textContent = content; }
    else {
        div.innerHTML = DOMPurify.sanitize(marked.parse(content));
        const agentColor = agentColors[selectedAgent];
        if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
    }

    addCopyBtn(div, content);
    addTimestamp(div, ts);
    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    chat.appendChild(div);
    while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
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
                item.addEventListener('click', () => {
                    const input = $('#chat-input');
                    input.value += (input.value ? '\n' : '') + f.path;
                    input.focus();
                });
                container.appendChild(item);
            }
        }
        if (files.length === 0) {
            container.innerHTML = '<div class="text-slate-600 px-2 italic">empty</div>';
        }
    } catch (e) {
        container.innerHTML = `<div class="text-red-400 px-2">${e.message}</div>`;
    }
}

function initFilePanel() {
    const panel = $('#file-panel');
    const tree = $('#file-tree');
    const toggle = $('#file-panel-toggle');

    if (toggle) {
        toggle.addEventListener('click', () => {
            panel.classList.toggle('hidden');
            toggle.textContent = panel.classList.contains('hidden') ? '▶' : '◀';
        });
    }

    // Drag over chat input
    const chatInput = $('#chat-input');
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

    try {
        if (!currentScope) return;

        const [sessions, stats] = await Promise.all([
            api(`/api/sessions?scope=${encodeURIComponent(currentScope)}`, { signal }),
            api(`/api/stats?scope=${encodeURIComponent(currentScope)}`, { signal }),
        ]);

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
