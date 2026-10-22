"""Quota gate reasons: the panel renders a stable server `reason_key` through i18n.js."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
QUOTA_LINES = (ROOT / "app/static/js/quota-lines.js").read_text(encoding="utf-8")
I18N = ROOT / "app/static/js/i18n.js"


def _templates() -> dict[str, str]:
    block = re.search(r"const _QL_REASONS = \{(.*?)\n\};", QUOTA_LINES, re.S).group(1)
    pairs = re.findall(r"^\s*(\w+): (['\"])(.*)\2,\s*$", block, re.M)
    return {key: template for key, _, template in pairs}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _page(browser, language):
    context = browser.new_context()
    context.add_init_script(f"localStorage.setItem('orch_lang', '{language}')")
    page = context.new_page()
    page.route("http://harness.local/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<body></body>"))
    page.goto("http://harness.local/")
    page.add_script_tag(path=str(I18N))
    return context, page


def test_every_server_reason_key_has_a_template():
    from app.quota_gate import evaluate_worker_admission  # noqa: F401  (import guard)
    source = (ROOT / "app/quota_gate.py").read_text(encoding="utf-8")
    server_keys = set(re.findall(r'reason_key(?:=|\s*=\s*)"(\w+)"', source))
    server_keys.discard("unknown")
    assert server_keys
    assert server_keys <= set(_templates())


def test_english_dictionary_has_every_reason_template_and_english_stays_verbatim(browser):
    templates = _templates()
    assert templates
    results = {}
    for language in ("en", "ru"):
        context, page = _page(browser, language)
        try:
            results[language] = page.evaluate(
                """(templates) => Object.fromEntries(templates.map(t => [t, {
                    shown: T(t, {util: '90', limit: '42', hard_stop: '99', norm: '40',
                                 tolerance: '2', lane: 'sol', seconds: '5', label: 'X',
                                 reset_at: 'R', error: 'E'}),
                    inDict: Object.prototype.hasOwnProperty.call(window.orchDict, t),
                }]))""",
                list(templates.values()),
            )
        finally:
            context.close()

    for template in templates.values():
        en, ru = results["en"][template], results["ru"][template]
        assert ru["inDict"], f"missing Russian entry for: {template}"
        assert "{" not in en["shown"] and "{" not in ru["shown"]
        assert not re.search(r"[А-Яа-яЁё]", en["shown"]), en["shown"]
        assert re.search(r"[А-Яа-яЁё]", ru["shown"]), ru["shown"]
