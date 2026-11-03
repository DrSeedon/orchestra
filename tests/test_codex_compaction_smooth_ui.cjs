// Execute the production compaction indicator, Stop and restart-cli confirmations and
// the SSE hook with isolated UI doubles. No browser, server, provider or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '../app/static/js', name), 'utf8');
const sources = {chat: read('chat.js'), app: read('app.js')};
function body(file, name) {
    const source = sources[file];
    let start = source.indexOf(`function ${name}(`);
    if (start < 0) throw Error(`missing function ${name}`);
    if (source.slice(start - 6, start) === 'async ') start -= 6;
    const end = source.indexOf('\n}', start) + 2;
    return source.slice(start, end);
}

class ClassList {
    constructor(...names) { this.names = new Set(names); }
    add(name) { this.names.add(name); }
    remove(name) { this.names.delete(name); }
    contains(name) { return this.names.has(name); }
}
const indicator = {textContent: '', classList: new ClassList('hidden')};
const restartButton = {textContent: '♻️', disabled: false};
const calls = [];
const confirms = [];
let confirmAnswer = false;
const intervals = new Map();
let nextInterval = 1;
const context = vm.createContext({
    selectedAgent: 'orch', currentScope: '/scope', _compactionState: null, _compactionClock: null,
    Date, Number, Math,
    T: (text, params = {}) => text.replace(/\{(\w+)\}/g, (_m, key) => String(params[key])),
    $: selector => ({'#compaction-indicator': indicator, '#restart-cli-btn': restartButton})[selector],
    confirm: message => { confirms.push(message); return confirmAnswer; },
    alert: () => {},
    setTimeout: () => {},
    setInterval: (fn, ms) => { const id = nextInterval++; intervals.set(id, {fn, ms}); return id; },
    clearInterval: id => intervals.delete(id),
    api: async (url, options) => { calls.push([url, JSON.parse(options.body)]); return {ok: true}; },
});
vm.runInContext([
    body('chat', 'compactionIndicatorText'), body('chat', 'applyCompactionState'),
    body('chat', 'confirmStopWhileCompacting'), body('chat', 'stopAgent'),
    body('app', 'restartCli'),
].join('\n'), context);

(async () => {
    // Not compacting: Stop and restart-cli act at once, without a question.
    await context.stopAgent();
    await context.restartCli();
    assert.deepEqual(confirms, []);
    assert.deepEqual(calls.map(call => call[0]), [
        '/api/sessions/orch/interrupt', '/api/sessions/orch/restart-cli',
    ]);
    assert(indicator.classList.contains('hidden'));

    // Compaction started 75 s ago: a visible indicator with elapsed time and a clock.
    const startedAt = Date.now() / 1000 - 75;
    context.applyCompactionState('orch', {kind: 'codex_turn', started_at: startedAt});
    assert(!indicator.classList.contains('hidden'));
    assert.match(indicator.textContent, /Codex is compacting context · 7[5-6] s elapsed · usually 1–4 min/);
    assert.equal(intervals.size, 1);
    assert.equal([...intervals.values()][0].ms, 1000);
    assert.equal(context.compactionIndicatorText({started_at: 100}, 160_000).includes('60 s'), true);

    // While compacting both buttons ask; "no" keeps the agent running.
    calls.length = 0;
    confirmAnswer = false;
    await context.stopAgent();
    await context.restartCli();
    assert.equal(confirms.length, 2);
    assert.equal(calls.length, 0);
    assert.match(confirms[0], /^Codex is compacting context now \(usually 1–4 minutes\)\. If you stop it, compaction starts over\. Stop anyway\?$/);
    // "Yes" never blocks.
    confirmAnswer = true;
    await context.stopAgent();
    await context.restartCli();
    assert.deepEqual(calls.map(call => call[0]), [
        '/api/sessions/orch/interrupt', '/api/sessions/orch/restart-cli',
    ]);

    // Another agent's stream cannot paint this chat.
    context.applyCompactionState('other', null);
    assert(!indicator.classList.contains('hidden'));

    // Compaction over: hidden, the clock stopped, and Stop no longer asks.
    context.applyCompactionState('orch', null);
    assert(indicator.classList.contains('hidden'));
    assert.equal(indicator.textContent, '');
    assert.equal(intervals.size, 0);
    confirms.length = 0;
    await context.stopAgent();
    assert.deepEqual(confirms, []);
    console.log('PASS: compaction indicator and confirmations');

    // The real SSE handler forwards the server state on every event.
    const applied = [];
    const sse = vm.createContext({
        currentScope: '/scope', selectedAgent: 'orch', _chatLoadGeneration: 1, eventSource: null,
        _chatLoading: false, _chatSnapshotReady: true, scrollAfterLoad: false,
        _chatSessionId: 'session', chatLogs: {orch: {lastId: 1, firstId: 1}}, _CHAT_PAGE: 100,
        localMessages: new Set(), console,
        EventSource: class { constructor(url) { this.url = url; } close() {} },
        _armCallNotifications: () => {}, _applyLiveAgentStatus: () => {}, liveAgentStatus: () => {},
        _wakeStatusRefreshFromStream: () => {}, _maybeNotifyCall: () => {}, _chatAtBottom: () => false,
        _refreshContextAfterCompact: () => {}, addChatEntry: () => {}, _newChatLogState: () => ({}),
        applyCompactionState: (name, state) => applied.push([name, state]),
    });
    vm.runInContext(body('app', 'connectSSE'), sse);
    sse.connectSSE();
    const deliver = extra => sse.eventSource.onmessage({data: JSON.stringify({
        id: 2, session_id: 'session', type: 'status', agent_status: 'running',
        content: 'codex compacting context', ...extra,
    })});
    deliver({compaction: {kind: 'codex_turn', started_at: 1}});
    deliver({compaction: null});
    deliver({compaction: {kind: 'orchestra', started_at: 2}});
    deliver({});  // no live session behind the stream: nothing can be compacting
    // JSON.parse ran inside the VM realm: compare by value, not by prototype.
    assert.equal(JSON.stringify(applied), JSON.stringify([
        ['orch', {kind: 'codex_turn', started_at: 1}], ['orch', null],
        ['orch', {kind: 'orchestra', started_at: 2}], ['orch', null],
    ]));
    console.log('PASS: SSE forwards compaction state');

    // The 3 s /api/sessions poll is the channel that clears the bar when the stream is
    // silent (session unloaded); a reply without the field (old server) changes nothing.
    const polled = [];
    const poll = vm.createContext({
        refreshInProgress: false, refreshController: null, AbortController: class { abort() {} },
        currentScope: '/scope', selectedAgent: 'orch', eventSource: {}, console,
        Date, _orchFreshAt: Date.now(), _ORCH_REFRESH_MS: 3_600_000,
        api: async url => (url.startsWith('/api/sessions') ? pollSessions : {}),
        _renderSessionsAndStats: () => {}, snapshotSave: () => {}, Connection: {clear: () => {}},
        updateStopButton: () => {}, removeWaitingIndicator: () => {}, connectSSE: () => {},
        _restoreSessionsSnapshot: () => {},
        applyCompactionState: (name, state) => polled.push([name, state]),
    });
    let pollSessions = [{name: 'orch', status: 'running', compaction: {kind: 'orchestra', started_at: 3}}];
    vm.runInContext(body('app', 'refreshSessions'), poll);
    await poll.refreshSessions();
    pollSessions = [{name: 'orch', status: 'idle', compaction: null}];
    await poll.refreshSessions();
    pollSessions = [{name: 'orch', status: 'idle'}];
    await poll.refreshSessions();
    assert.equal(JSON.stringify(polled), JSON.stringify([
        ['orch', {kind: 'orchestra', started_at: 3}], ['orch', null],
    ]));
    console.log('PASS: session poll applies compaction state');

    // Switching agents drops the previous agent's bar and its Stop question.
    context.applyCompactionState('orch', {kind: 'codex_turn', started_at: startedAt});
    assert(!indicator.classList.contains('hidden'));
    Object.assign(context, {
        _resetChatView: () => {}, liveResetActivity: () => {}, localMessages: new Set(),
        clearTimeout: () => {}, cancelAnimationFrame: () => {}, _resetCodexActivityState: () => {},
        uiDebounceTimer: null, _streamRafId: null,
    });
    vm.runInContext(body('chat', 'resetChatTransientState'), context);
    context.resetChatTransientState();
    assert(indicator.classList.contains('hidden'));
    assert.equal(intervals.size, 0);
    confirms.length = 0;
    context.selectedAgent = 'other';
    await context.stopAgent();
    assert.deepEqual(confirms, []);
    console.log('PASS: agent switch clears compaction state');
})().catch(error => { console.error(error); process.exitCode = 1; });
