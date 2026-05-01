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

const $ = (s) => document.querySelector(s);

document.addEventListener('DOMContentLoaded', () => {
    $('#send-btn').addEventListener('click', sendChat);
    $('#chat-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $('#orch-picker').addEventListener('change', onOrchestratorChange);
    $('#new-orch-btn').addEventListener('click', () => {
        $('#new-orch-modal').classList.remove('hidden');
        $('#new-orch-modal').classList.add('flex');
        $('#orch-name').focus();
    });
    $('#modal-close').addEventListener('click', closeModal);
    $('#new-orch-modal').addEventListener('click', (e) => {
        if (e.target === $('#new-orch-modal')) closeModal();
    });
    $('#create-orch-btn').addEventListener('click', createOrchestrator);
    $('#orch-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#orch-cwd').focus(); });
    $('#orch-cwd').addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
    loadModels();
    loadOrchestrators();
    scheduleRefresh();
});

function scheduleRefresh() {
    const isWaiting = !!$('#waiting-indicator');
    const delay = isWaiting ? 500 : 3000;
    setTimeout(async () => {
        await refresh();
        scheduleRefresh();
    }, delay);
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
        await loadOrchestrators();
        $('#orch-picker').value = cwd; onOrchestratorChange();
    } catch (e) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    finally { btn.disabled = false; btn.textContent = 'Create Orchestrator'; }
}

// === Orchestrator Picker ===
async function loadOrchestrators() {
    try {
        const data = await api('/api/orchestrators');
        const picker = $('#orch-picker');
        picker.innerHTML = '';
        for (const o of data) {
            const opt = document.createElement('option');
            opt.value = o.scope;
            opt.dataset.id = o.id;
            opt.dataset.name = o.name;
            opt.textContent = `${o.name} — ${o.scope.split('/').slice(-2).join('/')}`;
            picker.appendChild(opt);
        }
        if (data.length > 0 && !currentScope) {
            picker.value = data[0].scope;
            onOrchestratorChange();
        }
    } catch {}
}

function onOrchestratorChange() {
    const picker = $('#orch-picker');
    const opt = picker.selectedOptions[0];
    currentScope = picker.value || null;
    chatLogs = {};
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    selectedAgent = opt?.dataset?.name || null;
    $('#chat').innerHTML = '';
    scrollAfterLoad = true;
    updateAgentInfo(null);
    refresh();
}

// === Agent Selection ===
function selectAgent(name) {
    selectedAgent = name;
    streamBubble = null;
    streamContent = '';
    $('#chat').innerHTML = '';
    if (chatLogs[name]) chatLogs[name].lastId = 0;
    scrollAfterLoad = true;
    updateInputState();
    renderAgentList();
    fetchAgentContext(name);
    refresh();
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
    return `${pct}% (${totalK}/${maxK})`;
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

    const active = sessions.filter(s => s.status !== 'stopped' && s.status !== 'error');
    const archive = sessions.filter(s => s.status === 'stopped' || s.status === 'error');

    for (const s of active) {
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
    statusEl.className = `text-xs font-mono status-${s.status}`;
    statusEl.textContent = `● ${s.status}`;
    nameRow.append(nameEl, statusEl);

    const meta = document.createElement('div');
    meta.className = 'text-xs text-slate-600 mt-0.5';
    meta.textContent = s.model || '';

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
    const div = document.createElement('div');
    div.id = 'waiting-indicator';
    div.className = 'flex items-center gap-2 text-xs text-slate-500 py-2 px-3';
    div.innerHTML = '<span class="waiting-dots"><span>.</span><span>.</span><span>.</span></span> waiting for response';
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function removeWaitingIndicator() {
    const el = $('#waiting-indicator');
    if (el) el.remove();
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

    const div = document.createElement('div');
    div.className = `px-3 py-2 rounded-lg text-sm break-words ${
        type === 'user_message' ? 'chat-user ml-16' :
        type === 'tool' ? 'chat-tool' :
        type === 'tool_result' ? 'chat-tool-result' :
        type === 'error' ? 'text-red-400 text-xs' :
        'chat-bot markdown-body'
    }`;
    if (type === 'user_message') { div.textContent = content; }
    else if (type === 'tool') { div.textContent = `🔧 ${content}`; }
    else if (type === 'tool_result') { div.innerHTML = '📎 ' + DOMPurify.sanitize(marked.parse(content)); }
    else if (type === 'error') { div.textContent = content; }
    else { div.innerHTML = DOMPurify.sanitize(marked.parse(content)); }

    addCopyBtn(div, content);
    addTimestamp(div, ts);
    const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
    chat.appendChild(div);
    while (chat.children.length > MAX_CHAT_NODES) chat.removeChild(chat.firstChild);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

// === Refresh Loop ===
let refreshInProgress = false;
async function refresh() {
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

        if (selectedAgent) {
            const agentSession = sessions.find(s => s.name === selectedAgent);
            if (agentSession) {
                if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0 };
                const afterId = chatLogs[selectedAgent].lastId;
                const logs = await api(`/api/sessions/${selectedAgent}/logs?scope=${encodeURIComponent(currentScope)}&after_id=${afterId}`, { signal });
                for (const l of logs) {
                    if (l.type === 'user_message' && localMessages.has(l.content)) {
                        localMessages.delete(l.content);
                    } else {
                        addChatEntry(l.type, l.content, l.ts);
                    }
                    if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                }

                if (agentSession.status === 'running' && !$('#waiting-indicator')) {
                    showWaitingIndicator();
                } else if (agentSession.status !== 'running') {
                    removeWaitingIndicator();
                }

                if (scrollAfterLoad) {
                    scrollAfterLoad = false;
                    $('#chat').scrollTop = $('#chat').scrollHeight;
                }
            }
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
