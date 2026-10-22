"""Execute the worker-card quota warning offline, including hostile parent/reason text."""

import json
from pathlib import Path
import shutil
import subprocess


def test_worker_card_and_status_detail_display_quota_hold_as_text():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app/static/js/app.js").read_text()
    utils = (root / "app/static/js/utils.js").read_text()
    helpers = utils[utils.index("function _runtimeStatusDetail("):utils.index("// Client task/payment")]
    card = app[app.index("function createAgentItem("):app.index("function _applyLiveAgentStatus(")]
    script = r'''
const assert = require('assert/strict');
const code = JSON.parse(require('fs').readFileSync(0, 'utf8'));
class Element {
    constructor() { this.children=[]; this.dataset={}; this.style={}; }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.children.push(node); return node; }
    addEventListener() {}
}
const document = {createElement() { return new Element(); }};
const selectedAgent = 'another-worker';
const _roleIcons = {}, _STATUS_ICON = {idle:'○'}, _STATUS_TITLE = {idle:'idle'};
function T(text, args={}) {
    for (const [key, value] of Object.entries(args)) text = text.replaceAll('{'+key+'}', value);
    return text;
}
function _cachePill() { return null; }
function modelBadge() { return new Element(); }
function _modelReasonBadge() { return null; }
function isHubModel() { return false; }
eval(code.helpers);
eval(code.card);
const hold = {parent_name:'<img src=x onerror=alert(1)>', reason:'<script>bad()</script>', hint:'hubsol'};
const worker = {name:'worker', status:'idle', report_quota_hold:hold};
function warning(item) { return item.children[1].children.find(n => n.className?.includes('agent-report-hold')); }
const mark = warning(createAgentItem(worker));
assert.ok(mark);
assert.ok(mark.textContent.includes('Report held by quota gate'));
assert.ok(mark.textContent.includes(hold.parent_name));
assert.equal(mark.innerHTML, undefined);
assert.ok(mark.title.includes(hold.reason));
assert.ok(_runtimeStatusDetail(worker).includes(hold.parent_name));
assert.equal(warning(createAgentItem({name:'worker',status:'idle'})), undefined);
assert.equal(_runtimeStatusDetail({}), '');
'''
    result = subprocess.run(
        [shutil.which("node"), "-e", script], input=json.dumps(dict(helpers=helpers, card=card)),
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
