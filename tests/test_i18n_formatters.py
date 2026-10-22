"""Locale selection must be shared by every dashboard formatter."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app/static/js"


def test_all_dashboard_locale_formatters_use_ui_language():
    calls = re.compile(
        r"(?:\.toLocale(?:String|DateString|TimeString)|"
        r"Intl\.(?:DateTimeFormat|NumberFormat))\s*\(([^\n]*)"
    )
    failures = []
    for path in JS.rglob("*.js"):
        for match in calls.finditer(path.read_text()):
            if not match[1].lstrip().startswith("orchLocale()"):
                failures.append(f"{path.name}: {match[0]}")
    assert not failures, "Formatters bypass the UI locale helper:\n" + "\n".join(failures)


def test_ui_locale_formatters_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    result = subprocess.run(
        [node, "-e", NODE_CHECK], cwd=ROOT, text=True,
        capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


NODE_CHECK = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function load(context, name) {
    vm.runInContext(fs.readFileSync('app/static/js/' + name, 'utf8'), context);
}
for (const language of ['ru', 'en']) {
    // Deliberately use a browser language different from the selected UI language.
    const context = vm.createContext({
        window: null,
        document: {body: {dataset: {}}, documentElement: {}, readyState: 'loading',
                   addEventListener() {}},
        localStorage: {getItem: () => language},
        navigator: {language: language === 'en' ? 'ru-RU' : 'en-US'},
        marked: {parse: x => x, setOptions() {}},
        DOMPurify: {addHook() {}},
    });
    context.window = context;
    for (const name of ['i18n.js', 'utils.js', 'usage.js', 'analytics.js', 'jobs-timeline.js']) {
        load(context, name);
    }
    const app = fs.readFileSync('app/static/js/app.js', 'utf8');
    const chat = fs.readFileSync('app/static/js/chat.js', 'utf8');
    vm.runInContext(app.match(/function fmtCost\(v\) \{[\s\S]*?\n\}/)[0], context);
    vm.runInContext(chat.match(/function _taskMoney\(value\) \{[\s\S]*?\n\}/)[0], context);
    const values = vm.runInContext(`({
        lang: orchLang(), locale: orchLocale(),
        cost: fmtCost(12.3), tinyCost: fmtCost(0.0012), taskMoney: _taskMoney(1234.5),
        money: _analyticsMoney(1234.5), zero: _analyticsMoney(0),
        small: _analyticsMoney(0.12), invalid: _analyticsMoney(null),
        number: _analyticsNumber(1234.5),
        date: _analyticsDateTime('2026-10-06T12:15:00Z'),
        reset: _krskReset('2026-10-06T12:15:00Z'),
        jobs: JobsView.krsk(new Date('2026-10-06T12:15:00Z')),
        invalidReset: _krskReset('invalid'),
    })`, context);
    assert.equal(values.lang, language);
    assert.equal(values.locale, language === 'ru' ? 'ru-RU' : 'en-US');
    assert.equal(values.cost, language === 'ru' ? '$12,30' : '$12.30');
    assert.equal(values.tinyCost, language === 'ru' ? '$0,0012' : '$0.0012');
    assert.equal(values.taskMoney, language === 'ru' ? '1\u00a0234,5' : '1,234.5');
    assert.equal(values.invalid, '—');
    assert.equal(values.invalidReset, '');
    assert.equal(values.zero, language === 'ru' ? '$0,00' : '$0.00');
    assert.equal(values.small, language === 'ru' ? '$0,12' : '$0.12');
    assert.equal(values.money, language === 'ru' ? '$1\u00a0234,5' : '$1,234.5');
    assert.equal(values.number, language === 'ru' ? '1\u00a0234,5' : '1,234.5');
    for (const key of ['date', 'reset', 'jobs']) {
        assert.match(values[key], language === 'ru' ? /окт/i : /Oct/);
    }
    assert.match(values.reset, language === 'ru' ? /вт/i : /Tue/);
    assert.match(values.reset, /19:15/);
    assert.match(values.jobs, /19:15/);
    // The helper reads the current language on each call, rather than caching it.
    context.orchLang = () => language === 'en' ? 'ru' : 'en';
    assert.equal(vm.runInContext('orchLocale()', context), language === 'en' ? 'ru-RU' : 'en-US');
}
console.log('RU/EN locale, money, dates, time zones and invalid inputs: passed');
"""
