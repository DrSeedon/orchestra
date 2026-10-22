"""Execute dashboard rendering and selection logic offline with a minimal DOM."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest


def test_reason_is_visible_next_to_model_and_claude_selection_requires_input():
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (Path(__file__).resolve().parents[1] / 'app/static/js/app.js').read_text()
    helpers = source[source.index('function _modelReasonForSelection('):source.index('async function _showModelPicker(')]
    header = source[source.index("    const modelEl = $('#ai-model');"):source.index('    let changeBtn =', source.index("    const modelEl = $('#ai-model');"))]
    card_start = source.index("    meta.appendChild(modelBadge(s.model || ''));")
    card = source[card_start:source.index('    if (isHubModel', card_start)]
    script = r'''
const assert = require('assert/strict');
const parts = JSON.parse(require('fs').readFileSync(0,'utf8'));
function T(s) { return s; }
const document = {
    createElement() { return {style:{}, dataset:{}}; },
    getElementById() { return null; },
};
const window = { prompt() { throw Error('Unexpected prompt for Sol or own models'); } };
eval(parts.helpers);
assert.equal(_modelReasonForSelection('hub-gpt-6.1-sol'), '');
assert.equal(_modelReasonForSelection('claude-sonnet-5-5[1m]'), '');
window.prompt = () => null;
assert.equal(_modelReasonForSelection('hub-claude-sonnet-5-5'), null);
window.prompt = () => '   ';
assert.equal(_modelReasonForSelection('hub-claude-opus-5-5'), null);
window.prompt = () => '  Creative scene direction  ';
assert.equal(_modelReasonForSelection('hub-claude-haiku-5-5'), 'Creative scene direction');
const reason = '<img src=x onerror=alert(1)> creative direction';
const badge = _modelReasonBadge(reason);
assert.equal(badge.textContent, reason);
assert.equal(badge.innerHTML, undefined);  // Reason is treated as data, not markup.
assert.equal(badge.title, 'Model reason: ' + reason);
assert.equal(_modelReasonBadge(''), null);
const appended = [];
const modelElement = {style:{}, after(node) { appended.push(node); }};
function $(selector) { assert.equal(selector,'#ai-model'); return modelElement; }
function modelColorVar() { return 'color'; }
const session = {model:'hub-claude-sonnet-5-5', model_reason:reason};
eval(parts.header);
assert.equal(modelElement.textContent, session.model);
assert.equal(appended.length, 1);
assert.equal(appended[0].textContent, reason);
const children = [];
const meta = {appendChild(node) { children.push(node); }};
function modelBadge(model) { return {textContent:model}; }
const s = session;
eval(parts.card);
assert.deepEqual(children.map(n => n.textContent), [session.model, reason]);
console.log('header/card reason and model selection: passed');
'''
    result = subprocess.run([node, '-e', script], input=json.dumps(dict(helpers=helpers, header=header, card=card)),
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
