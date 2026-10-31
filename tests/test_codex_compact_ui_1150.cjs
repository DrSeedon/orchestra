// Execute the actual SSE handler and context functions with isolated UI adapters.
// No browser, HTTP server, provider, npm dependencies or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/app.js'), 'utf8');
function body(name) {
    let start = source.indexOf(`function ${name}(`);
    if (start < 0) throw Error(`missing function ${name}`);
    if (source.slice(start - 6, start) === 'async ') start -= 6;
    const end = source.indexOf('\n}', start) + 2;
    return source.slice(start, end);
}
const noop = () => {};
const fetches = [];
const rendered = [];
const translations = [];
const context = vm.createContext({
    currentScope: '/scope', selectedAgent: 'worker', _chatLoadGeneration: 1,
    _chatLoading: false, _chatSnapshotReady: true, eventSource: null, _chatSessionId: 'session',
    chatLogs: {worker: {lastId: 1, firstId: 1}}, _CHAT_PAGE: 100,
    contextCache: {'/scope:worker': '70%', '/other:worker': 'newer context'},
    localMessages: new Set(), scrollAfterLoad: false,
    T: key => { translations.push(key); return `translation#${translations.length}`; },
    console: {warn: (...args) => { throw Error(args.join(' ')); }},
    EventSource: class { constructor(url) { this.url = url; } close() {} },
    _armCallNotifications: noop, _applyLiveAgentStatus: noop, liveAgentStatus: noop,
    _wakeStatusRefreshFromStream: noop, _maybeNotifyCall: noop, _chatAtBottom: () => false,
    fetchAgentContext: name => fetches.push(name),
    addChatEntry: (...args) => rendered.push(args),
});
vm.runInContext(['connectSSE', '_refreshContextAfterCompact', 'formatContext'].map(body).join('\n'), context);
context.connectSSE();
const sourceStream = context.eventSource;
function deliver(content, extra = {}) {
    sourceStream.onmessage({data: JSON.stringify({
        id: 2, session_id: 'session', type: 'status', agent_status: 'idle', content, ...extra,
    })});
}
deliver('native Codex compact failed: timeout');
assert.equal(fetches.length, 0);
assert.equal(context.contextCache['/scope:worker'], '70%');
deliver('compact done (native Codex): 70% → 1%');
assert.deepEqual(fetches, ['worker']);
assert.equal(context.contextCache['/scope:worker'], undefined);
assert.equal(rendered.length, 2); // original error remains; success is a separate observation
const unknown = context.formatContext({known: false, percentage: 70, total_tokens: 70000});
assert.equal(translations.length, 1);
assert.equal(unknown, 'translation#1');
assert(!unknown.includes('70')); // old usage cannot leak through unknown formatting
assert.equal(context.formatContext({known: true, percentage: 1, total_tokens: 1200, max_tokens: 100000}), '1% (1k/100k)');
context.currentScope = '/other';
deliver('compact done (native Codex): 70% → 1%');
assert.equal(fetches.length, 1);
assert.equal(context.contextCache['/other:worker'], 'newer context');
context.currentScope = '/scope';
context._chatLoadGeneration++;
deliver('compact done (native Codex): 70% → 1%');
assert.equal(fetches.length, 1);
console.log('PASS: actual SSE compact publication, cache refresh, unknown usage and stale-stream guards');

// The real button uses the long-call option, without changing the generic API
// default or replaying a failed non-idempotent request.
vm.runInContext(body('compactAgent'), context);
const button = {};
context.$ = () => button;
context.setTimeout = noop;
context.api = async (url, options) => {
    assert.equal(url, '/api/sessions/worker/compact');
    assert.equal(options.method, 'POST');
    assert(options.timeoutMs > 600000 && options.timeoutMs <= 660000);
    return {ok: true};
};
context.compactAgent().then(() => {
    assert.equal(button.textContent, '✅');
    console.log('PASS: actual compact button waits for the bounded backend budget');
}).catch(error => { console.error(error); process.exitCode = 1; });
