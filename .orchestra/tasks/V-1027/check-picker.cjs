const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static/js/app.js', 'utf8');
const test = fs.readFileSync('tests/test_frontend.py', 'utf8');
const setup = test.match(/page\.evaluate\("""(\(\{model, reason\}\) => \{[\s\S]*?)""",/)[1];
const helper = source.split('function _modelReasonForSelection')[1].split('function _modelReasonBadge')[0];
const picker = source.split('async function _showModelPicker')[1].split('function updateAgentInfo')[0];
const functions = 'function _modelReasonForSelection' + helper + 'async function _showModelPicker' + picker;

class Element {
    constructor() { this.style = {}; this.children = []; this.listeners = {}; }
    getBoundingClientRect() { return {left: 0, bottom: 0}; }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    appendChild(child) { this.children.push(child); }
    remove() {}
}

async function check(code, model, reason) {
    const anchor = new Element();
    const label = new Element();
    const document = {
        body: new Element(),
        getElementById: () => null,
        createElement: () => new Element(),
        querySelector: selector => ({'#anchor': anchor, '#ai-model': label})[selector],
    };
    const context = vm.createContext({document, console, setTimeout: () => {}});
    context.window = context;
    vm.runInContext('(' + setup + ')', context)({model, reason});
    vm.runInContext(code, context);
    await context._showModelPicker('picker-worker', 'claude-opus-5-5', anchor);
    await document.body.children[0].children[0].listeners.click({stopPropagation() {}});
    const body = {model, scope: 'picker-test-scope'};
    if (reason !== null) body.model_reason = reason;
    assert.deepEqual(JSON.parse(JSON.stringify(context.requests)), [{
        url: '/api/sessions/picker-worker/change-model', method: 'POST', body,
    }]);
}

(async () => {
    for (const [model, reason] of [
        ['claude-sonnet-5-5[1m]', null],
        ['hub-gpt-6.1-sol', null],
        ['hub-claude-sonnet-5-5', 'Creative scene direction'],
    ]) {
        await check(functions, model, reason);
        console.log('PASS request:', model);
    }
    for (const [name, before, after] of [
        ['missing model', 'model: m.id, scope: currentScope', 'scope: currentScope'],
        ['missing scope', 'model: m.id, scope: currentScope', 'model: m.id'],
        ['missing reason', 'if (reason) body.model_reason = reason;', ''],
    ]) {
        assert.ok(functions.includes(before));
        await assert.rejects(check(functions.replace(before, after), 'hub-claude-sonnet-5-5', 'Creative scene direction'), assert.AssertionError);
        console.log('PASS rejected mutation:', name);
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
