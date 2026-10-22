"""Dashboard capacity must use the pool's usable count, independent of the active account."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dashboard_shows_usable_accounts_for_each_provider():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    source = (Path(__file__).resolve().parents[1] / "app/static/js/usage.js").read_text()
    function = source[source.index("function _hubPoolHtml("):source.index("async function _loadHubPool(")]
    checked = subprocess.run([node, "-e", r'''
const fs = require('fs');
const assert = require('assert/strict');
function T(key, values = {}) {
    return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{${name}}`, value), key);
}
function escHtml(value) { return String(value); }
function _hubPoolWindowHtml() { return ''; }
eval(fs.readFileSync(0, 'utf8'));
const html = _hubPoolHtml({available:true, providers:{
    claude:{accounts:10, creds_loaded:10, usable:0},
    codex:{accounts:4, creds_loaded:1, usable:3},
}});
assert.match(html, /claude.*0\/10 accounts usable/);
assert.match(html, /codex.*3\/4 accounts usable/);
assert.match(_hubPoolHtml({available:false}), /Hub pool unavailable/);
console.log('dashboard usable counts: passed');
'''], input=function, text=True, capture_output=True, timeout=15)
    assert checked.returncode == 0, checked.stdout + checked.stderr
