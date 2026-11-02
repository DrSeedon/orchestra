"""Execute dashboard rendering and selection logic offline with a minimal DOM."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest
from playwright.sync_api import Browser


def test_reason_stays_in_info_only_and_claude_selection_requires_input():
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
assert.deepEqual(children.map(n => n.textContent), [session.model]);
assert.equal(session.model_reason, reason);
console.log('info-only reason and model selection: passed');
'''
    result = subprocess.run([node, '-e', script], input=json.dumps(dict(helpers=helpers, header=header, card=card)),
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.browser
@pytest.mark.parametrize('width', [240, 320])
@pytest.mark.parametrize('model', ['gpt-6.1-sol', 'hub-gpt-6.1-sol'])
def test_agent_card_without_reason_preserves_layout_and_actions(browser: Browser, width, model):
    """Render the production card and styles with synthetic data, without a server."""
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app/static/js/app.js').read_text()
    card = source[source.index('function createAgentItem('):source.index('function _applyLiveAgentStatus(')]
    cache = source[source.index('function _cachePillState('):source.index('// Client-side countdown')]
    reason = source[source.index('function _modelReasonBadge('):source.index('async function _showModelPicker(')]
    utils = (root / 'app/static/js/utils.js').read_text()
    runtime = utils[utils.index('function _runtimeStatusDetail('):utils.index('// Client task/payment')]
    page = browser.new_page(viewport={'width': width, 'height': 600})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/*', lambda route: route.abort())
    page.set_content('<div class="tree-children"><div id="agent-list"></div></div>')
    for css in ('vendor/tailwind.css', 'design-system.css', 'style.css'):
        page.add_style_tag(path=str(root / 'app/static/css' / css))
    page.add_script_tag(content="""
        const T = (text, values = {}) => Object.entries(values).reduce(
            (out, [key, value]) => out.replaceAll(`{${key}}`, value), text);
        const selectedAgent = null;
        const _roleIcons = {worker: '⚙️'};
        const orchLocale = () => 'en-US';
        const fmtCost = value => '$' + value.toFixed(2);
        const selectAgent = name => { window.clickedAgent = name; };
        const _showAgentContextMenu = (event, session) => {
            window.contextAgent = session.name;
        };
        const _MODELS = [{id:'gpt-6.1-sol', label:'GPT', provider:'openai'},
            {id:'hub-gpt-6.1-sol', label:'GPT', provider:'openai'}];
    """)
    page.add_script_tag(path=str(root / 'app/static/js/theme.js'))
    page.add_script_tag(content=runtime + cache + reason + card)
    session = dict(
        id=1199, name='layout-worker', role='worker', status='running', model=model,
        description='Keep this stored description', model_reason='Gray explanation ' * 40,
        cost_usd=0.12, context_pct=42, color='#22c55e',
        checklist_progress=dict(total=3, completed=1, current='Check layout'),
        report_quota_hold=dict(parent_name='owner', reason='quota', hint='wait'),
        limit_wake=dict(label='Scheduled wake'),
    )
    result = page.evaluate("""session => {
        const original = JSON.stringify(session);
        const item = createAgentItem(session);
        document.querySelector('#agent-list').appendChild(item);
        const meta = item.querySelector('.ds-model').parentElement;
        const rect = meta.getBoundingClientRect();
        const withoutReason = createAgentItem({...session, model_reason: ''});
        return {
            unchanged: JSON.stringify(session) === original,
            identical: item.outerHTML === withoutReason.outerHTML,
            reasonCount: item.querySelectorAll('.model-reason').length,
            texts: Array.from(meta.children, node => node.textContent),
            fits: Array.from(meta.children).every(node => {
                const box = node.getBoundingClientRect();
                return box.left >= rect.left - 1 && box.right <= rect.right + 1;
            }),
            overflow: document.documentElement.scrollWidth > window.innerWidth,
            context: item.querySelector('[title="42% context"]').style.width,
        };
    }""", session)
    assert result == dict(
        unchanged=True, identical=True, reasonCount=0,
        texts=['🔥', 'GPT'] + (['Hub'] if model.startswith('hub-') else []) + ['$0.12'],
        fits=True, overflow=False, context='42%',
    )
    item = page.locator('.agent-item')
    assert item.get_attribute('data-session-id') == '1199'
    assert item.locator('.agent-status').inner_text() == '⚡ running'
    assert item.locator('.agent-checklist-summary').inner_text() == '1 of 3'
    assert item.locator('.agent-report-hold').inner_text() == 'Report held by quota gate → owner'
    assert item.locator('.agent-limit-wake').inner_text() == 'Scheduled wake'
    item.click()
    assert page.evaluate('window.clickedAgent') == session['name']
    item.click(button='right')
    assert page.evaluate('window.contextAgent') == session['name']
    assert errors == []
    page.close()
