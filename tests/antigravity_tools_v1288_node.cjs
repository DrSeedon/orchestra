// Offline DOM double: exercises production renderers, not layout or browser integration.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
        this.style = {}; this.className = ''; this._text = ''; this.parentNode = null;
        this.listeners = {};
        this.classList = {
            add: (...values) => { this.className += ' ' + values.join(' '); },
            remove: value => { this.className = this.className.split(' ').filter(c => c !== value).join(' '); },
            contains: value => this.className.split(' ').includes(value),
        };
    }
    set textContent(text) { this.replaceChildren(); this._text = String(text); }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    set innerHTML(html) { this.textContent = String(html).replace(/<[^>]*>/g, ''); this._html = html; }
    get innerHTML() { return this._html || this.textContent; }
    get firstChild() { return this.children[0] || null; }
    get lastElementChild() { return this.children.at(-1) || null; }
    get nextSibling() { return this.parentNode?.children[this.parentNode.children.indexOf(this) + 1] || null; }
    get previousElementSibling() { return this.parentNode?.children[this.parentNode.children.indexOf(this) - 1] || null; }
    get isConnected() { return this === body || Boolean(this.parentNode?.isConnected); }
    appendChild(child) { child.remove(); child.parentNode = this; this.children.push(child); return child; }
    append(...children) { children.forEach(c => this.appendChild(c)); }
    insertBefore(child, anchor) {
        child.remove(); child.parentNode = this;
        this.children.splice(this.children.indexOf(anchor), 0, child); return child;
    }
    after(child) { if (this.nextSibling) this.parentNode.insertBefore(child, this.nextSibling); else this.parentNode.appendChild(child); }
    remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(c => c !== this);
        this.parentNode = null;
    }
    replaceChildren(...children) {
        this.children.forEach(c => { c.parentNode = null; }); this.children = []; this._text = ''; this.append(...children);
    }
    setAttribute(name, value) { this[name] = String(value); }
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
    click() { for (const handler of this.listeners.click || []) handler({target: this, stopPropagation() {}}); }
    matches(selector) {
        const excluded = selector.match(/:not\(([^)]+)\)/);
        if (excluded) { if (this.matches(excluded[1])) return false; selector = selector.replace(excluded[0], ''); }
        const attrs = [...selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)];
        for (const [, key, expected] of attrs) {
            const value = key.startsWith('data-')
                ? this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] : this[key];
            if (value === undefined || (expected !== undefined && String(value) !== expected)) return false;
        }
        selector = selector.replace(/\[[^\]]+\]/g, '');
        const id = selector.match(/#([\w-]+)/);
        if (id && this.id !== id[1]) return false;
        for (const [, cls] of selector.matchAll(/\.([\w-]+)/g)) if (!this.classList.contains(cls)) return false;
        const tag = selector.match(/^[a-z]+/i);
        return !tag || this.tagName === tag[0].toUpperCase();
    }
    querySelectorAll(selector) {
        return this.children.flatMap(c => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const body = new Element('body');
const chat = new Element('div'); chat.id = 'chat'; body.appendChild(chat);
global.document = {body, createElement: tag => new Element(tag), addEventListener() {},
    querySelector: selector => body.querySelector(selector)};
global.window = global;
global.CSS = {escape: value => value};
global.$ = selector => body.querySelector(selector);
global.T = (text, args = {}) => text.replace(/\{(\w+)\}/g, (_, key) => args[key] ?? `{${key}}`);
global.DOMPurify = {sanitize: text => text};
global.marked = {parse: text => text};
global._escHtml = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;');
global.NOTIFY_USER_TOOL = 'mcp__orchestra__notify_user';
global.taskNum = value => String(value || '').replace(/^[A-Z]+-/, '');
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};

const root = path.resolve(__dirname, '..');
const mutations = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
for (const file of ['tool-renderers.js', 'live-activity.js', 'chat.js']) {
    let source = fs.readFileSync(path.join(root, 'app/static/js', file), 'utf8');
    if (mutations[file]) {
        const [before, after] = mutations[file];
        assert(source.includes(before), 'mutation anchor missing');
        source = source.replace(before, after);
    }
    vm.runInThisContext(source, {filename: file});
}
vm.runInThisContext(fs.readFileSync(path.join(root, 'app/static/css/vendor/diff_match_patch.js'), 'utf8'));

function call(name, input, compact = false, id = 'tool-1') {
    const content = input === undefined ? name : `${name}: ${JSON.stringify(input)}`;
    const card = compact ? buildCompactToolLine('tool', content, null, {tool_use_id: id}) : new Element('div');
    if (!compact) _renderFullToolCall(content, {tool_use_id: id}, card);
    chat.appendChild(card); return card;
}
function result(card, text, error = false) {
    if (card.dataset.compactTool) _updateCompactToolResult(card, text, false, error);
    else _renderFullToolResult(text, null, {tool_use_id: card.dataset.toolUseId, tool_is_error: error}, null,
        new Element('div'), div => chat.appendChild(div), false);
}
function reset() { chat.replaceChildren(); }
function preamble(body, newline = '\n') {
    return ['Created At: 2026-11-13T10:00:00Z', 'Completed At: 2026-11-13T10:00:01Z', body].join(newline);
}

const scenarios = {
    aliases() {
        for (const [raw, canonical] of Object.entries({run_command: 'Bash', read_file: 'Read',
            write_file: 'Write', edit_file: 'Edit', search_web: 'WebSearch', manage_task: 'Task'})) {
            assert.equal(canonicalToolName(raw), canonical);
            assert.equal(toolIcon(raw), toolIcon(canonical));
        }
        const input = {Path: 'a.py', StartLine: 4, EndLine: 8};
        const normalized = normalizeToolCall('read_file', input).input;
        assert.equal(normalized.file_path, 'a.py'); assert.equal(normalized.offset, 4); assert.equal(normalized.limit, 5);
        assert.equal(input.file_path, undefined, 'do not mutate caller input');
        assert.equal(normalizeToolInput({EndLine: 5}).limit, 5);
        for (const input of [{StartLine: 8, EndLine: 4}, {StartLine: -1, EndLine: 4}, {EndLine: '4'}]) {
            assert.equal(normalizeToolInput(input).limit, undefined);
        }
        assert.equal(normalizeToolInput({Path: 'old', file_path: 'new', limit: 2, EndLine: 5}).file_path, 'new');
        assert.equal(normalizeToolInput({limit: 2, EndLine: 5}).limit, 2);
        assert.equal(liveToolTimeoutMs('run_command', {WaitMsBeforeAsync: 10000}), 10000);
        assert.equal(liveToolTimeoutMs('run_command', {WaitMsBeforeAsync: 999999}), 600000);
        assert.equal(liveToolTimeoutMs('run_command', {IsDaemon: true}), 0);
        assert.equal(liveToolTimeoutMs('Bash', {}), 120000);
        assert.equal(liveToolTimeoutMs('Read', {timeout: 1000}), 0);
        reset();
        const compact = call('run_command', {CommandLine: 'printf hello', toolSummary: 'my command'}, true);
        assert.equal(compact.dataset.toolRaw, 'Bash');
        assert.equal(compact.querySelector('.compact-preview').textContent, 'printf hello');
        assert(compact.textContent.includes('my command'));
        const full = call('run_command', {CommandLine: 'printf hello', toolSummary: 'my command'});
        assert.equal(full.dataset.isBash, '1'); assert.equal(full.querySelector('pre').textContent, 'printf hello');
        assert(full.textContent.includes('my command'));
        const read = call('read_file', input, true);
        assert.equal(read.dataset.toolRaw, 'Read'); assert(read.textContent.includes('a.py :4 (5 lines)'));
    },
    mcp() {
        reset();
        const input = {ServerName: 'orchestra', ToolName: 'notify_user', Arguments: {reason: 'Need review'}};
        const full = call('call_mcp_tool', input);
        assert.equal(full.dataset.toolRawName, 'mcp__orchestra__notify_user');
        assert(full.classList.contains('chat-notify-user')); assert(full.textContent.includes('Need review'));
        assert(!full.textContent.includes('Call details unavailable'));
        const compact = call('call_mcp_tool', input, true);
        assert.equal(compact.dataset.toolRaw, 'mcp__orchestra__notify_user');
        assert(compact.classList.contains('chat-notify-user')); assert(compact.textContent.includes('Need review'));
        assert.equal(toolIcon(normalizeToolCall('call_mcp_tool', JSON.stringify(input)).name), '🎼');
        assert.deepEqual(normalizeToolCall('call_mcp_tool', {...input, Arguments: {}}).input, {});
        for (const bad of [{...input, ServerName: ''}, {...input, ToolName: ' '}, {...input, Arguments: []}]) {
            assert.equal(normalizeToolCall('call_mcp_tool', bad).name, 'call_mcp_tool');
        }
        for (const raw of ['call_mcp_tool', 'list_resources', 'read_resource']) {
            assert.notEqual(toolIcon(raw), '🔧'); assert.notEqual(toolShortName(raw), raw);
            assert(call(raw).textContent.includes(toolShortName(raw)));
        }
    },
    bash() {
        for (const newline of ['\n', '\r\n']) for (const rc of [0, 7, -1]) for (const compact of [false, true]) {
            reset();
            const card = call('run_command', {CommandLine: 'printf hi'}, compact);
            const output = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'].join(newline);
            const text = preamble(`Command exited with code ${rc}.${newline}${newline}Command output:${newline}${output}`, newline);
            result(card, text);
            assert(card.textContent.includes(rc === 0 ? '✓ 0' : `✗ exit ${rc}`));
            if (compact) assert.equal(card.dataset.resultContent, text, 'expansion retains the full result');
            else {
                const previews = card.querySelectorAll('pre');
                assert.equal(previews[1].textContent, 'first\nsecond\nthird\nfourth\nfifth');
                assert.equal(previews[2].textContent, 'sixth');
                assert(!card.textContent.includes('Created At:')); assert(!card.textContent.includes('Command output:'));
            }
        }
        for (const rc of [0, 2]) {
            reset(); const card = call('Bash', {command: 'true'});
            result(card, `exit_code=${rc}\nraw output`);
            assert(card.textContent.includes(rc === 0 ? '✓ 0' : '✗ exit 2'));
            assert.equal(card.querySelectorAll('pre')[1].textContent, 'raw output');
        }
        reset(); const silent = call('run_command', {CommandLine: 'true'});
        result(silent, preamble('Command exited with code 0.\n\nCommand output:\n'));
        assert.equal(silent.querySelectorAll('pre').length, 1);
    },
    read() {
        for (const filename of ['a.py', 'a.md', 'a.png']) for (const headers of [false, true]) {
            reset(); const card = call('read_file', {Path: filename, StartLine: 3, EndLine: 5});
            assert.equal(card.dataset.filePath, filename); assert.equal(card.dataset.isRead, '1');
            assert(card.querySelector('[data-role="read-skeleton"]'));
            result(card, headers ? preamble('1 lines, 1673 bytes') : '1 lines, 1673 bytes');
            assert.equal(card.querySelector('[data-role="read-skeleton"]'), null);
            assert.equal(card.querySelector('.read-stat')?.textContent, '1 lines, 1673 bytes');
            assert.equal(card.querySelectorAll('.diff-code').length, 0);
            assert(!card.textContent.includes('Created At:')); assert.equal(card.querySelector('img'), null);
        }
        for (const filename of ['a.py', 'a.md']) {
            reset(); const card = call('read_file', {Path: filename});
            result(card, preamble('Showing lines 3-4 of 9\r\n3:     first\r\n4: second', '\r\n'));
            assert.equal(card.querySelector('[data-role="read-skeleton"]'), null);
            assert(!card.textContent.includes('Showing lines')); assert(!card.textContent.includes('Created At:'));
            assert(!card.textContent.includes('3: ')); assert(card.textContent.includes('    first'));
        }
        reset(); const compact = call('read_file', {Path: 'a.py'}, true);
        result(compact, preamble('2 lines, 44 bytes')); assert(compact.textContent.includes('2 lines, 44 bytes'));
    },
    edit() {
        for (const compact of [false, true]) for (const name of ['edit_file', 'write_file']) {
            reset(); const input = name === 'edit_file' ? {Path: 'a.py', Target: 'before', Replacement: 'after'}
                : {Path: 'a.py', Content: 'after'};
            const card = call(name, input, compact);
            if (!compact) {
                assert.equal(card.dataset.isEdit, '1'); assert(card.querySelector('.diff-view'));
                assert(card.textContent.includes('after'));
            } else assert(card.textContent.includes('a.py'));
            result(card, 'permission denied', true);
            if (compact) { assert(card.textContent.includes('❌')); assert.equal(card.dataset.resultIsError, '1'); }
            else assert(card.textContent.includes('⚠️ permission denied'));
            assert(!card.textContent.includes('updated'));
        }
        for (const flag of [true, 1]) {
            reset(); const card = call('read_file', {Path: 'a.py'});
            result(card, 'not readable', flag);
            assert(card.textContent.includes('⚠️ not readable'));
            assert.equal(card.querySelector('[data-role="read-skeleton"]'), null);
        }
        // Compact expansion must carry an error flag even when there was no textual error wrapper.
        reset(); const compact = call('edit_file', {Path: 'a.py', Target: 'a', Replacement: 'b'}, true);
        result(compact, 'denied', true);
        const expanded = [];
        global.addChatEntry = (type, content, ts, anchor, payload) => {
            expanded.push({type, content, payload}); const card = new Element('div'); chat.insertBefore(card, anchor);
        };
        compact.click();
        assert.equal(expanded[1].payload.tool_is_error, true);
        assert.equal(expanded[1].content, 'denied');
    },
    legacy() {
        for (const [name, args] of [['Read', {file_path: 'a.py'}], ['read', {path: 'a.py'}],
            ['Edit', {file_path: 'a.py', old_string: 'old', new_string: 'new'}],
            ['write', {path: 'a.py', content: 'new'}]]) {
            reset(); const card = call(name, args); assert(card.querySelector('.diff-view'));
        }
        reset(); const raw = call('Bash', {command: 'echo raw'}); result(raw, 'raw\noutput');
        assert.equal(raw.querySelectorAll('pre')[1].textContent, 'raw\noutput');
        reset(); const read = call('Read', {file_path: 'a.py'}); result(read, '1\tplain\n2\tcode');
        assert.equal(read.querySelector('[data-role="read-skeleton"]'), null);
        assert(read.textContent.includes('plain'));
        reset(); const edit = call('Edit', {file_path: 'a.py', old_string: 'a', new_string: 'b'});
        result(edit, '<tool_use_error>legacy refusal</tool_use_error>');
        assert(edit.textContent.includes('⚠️ legacy refusal'));
        assert.equal(canonicalToolName('orchestra__notify_user'), 'mcp__orchestra__notify_user');
    },
};

const requested = process.argv[2] || 'all';
for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested === 'all' || requested === name) { scenario(); console.log(`PASS ${name}`); }
}
