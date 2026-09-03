"""#366 T5 — delivery check: the catalog screen must ship in the dashboard bundle.

Browser behaviour itself is verified manually via a Playwright page.route probe
(recorded in .orchestra/tasks/366/report.md); this test only proves the static bundle
carries the new screen and wires it to the T4 endpoints.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

APP_JS = Path(__file__).parent.parent / "app" / "static" / "js" / "app.js"
DASHBOARD_HTML = Path(__file__).parent.parent / "app" / "templates" / "dashboard.html"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _bundle() -> str:
    return APP_JS.read_text() + DASHBOARD_HTML.read_text()


def test_t5_catalog_screen_shipped():
    bundle = _bundle()
    assert 'id="catalog-modal"' in bundle or "'catalog-modal'" in bundle or \
        '"catalog-modal"' in bundle
    assert "/api/models/catalog" in bundle


def test_t5_catalog_screen_has_search_filters_and_toggles():
    bundle = _bundle().lower()
    for anchor in ("catalog-search", "catalog-free", "catalog-tools", "data-flag"):
        assert anchor in bundle, f"missing catalog UI anchor: {anchor}"


def test_t5_picker_reads_filtered_models_not_catalog():
    """The per-agent picker keeps consuming /api/models (already dashboard-filtered);
    the full catalog lives only on the catalog screen."""
    js = APP_JS.read_text()
    picker = js[js.index("async function _showModelPicker"):]
    picker = picker[:picker.index("\n}", picker.index("for (const m of"))]
    assert "_MODELS" in picker


def test_catalog_free_filter_and_admission_work_with_new_and_old_api_payloads(browser: Browser):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    html = """
        <input id="catalog-search">
        <input id="catalog-free" type="checkbox">
        <input id="catalog-tools" type="checkbox">
        <input id="catalog-image" type="checkbox">
        <div id="catalog-list"></div>
    """
    page.route("http://catalog.test/**", lambda route: route.fulfill(
        body=html, content_type="text/html",
    ))
    page.goto("http://catalog.test/")
    page.wait_for_load_state("networkidle")
    page.evaluate("""() => {
        window.$ = selector => document.querySelector(selector);
        window.MODEL_COST_CURRENCY = '$';
        window._MODELS = [];
        window._PROVIDER_COLORS = {};
    }""")
    page.add_script_tag(path=str(APP_JS))

    result = page.evaluate("""() => {
        const paid = {
            id: 'google/lyria-3-pro-preview', name: 'Lyria 3 Pro', runtime: 'harness',
            context_length: 1048576, price_prompt: 0, price_completion: 0,
            is_free: false, supports_tools: false, harness_eligible: false, available: true,
            input_modalities: ['text'], flags: {dashboard: false, agents: false},
        };
        const free = {
            id: 'thinkingmachines/inkling-small:free', name: 'Inkling Small', runtime: 'harness',
            context_length: 262144, price_prompt: 0, price_completion: 0,
            is_free: true, supports_tools: true, harness_eligible: true, available: true,
            input_modalities: ['text'], flags: {dashboard: false, agents: false},
        };
        const legacyFree = {
            id: 'poolside/laguna-s-2.1:free', name: 'Legacy Laguna', runtime: 'harness',
            context_length: 262144, price_prompt: 0, price_completion: 0,
            supports_tools: true, input_modalities: ['text'],
            flags: {dashboard: false, agents: false},
        };
        document.querySelector('#catalog-free').checked = true;
        const paidRow = _catalogRow(paid);
        const legacyRow = _catalogRow(legacyFree);
        return {
            paidMatches: _catalogMatches(paid),
            freeMatches: _catalogMatches(free),
            legacyFreeMatches: _catalogMatches(legacyFree),
            paidDisabled: paidRow.querySelectorAll('input:disabled').length,
            paidBlocked: paidRow.textContent.includes('blocked'),
            legacyDisabled: legacyRow.querySelectorAll('input:disabled').length,
        };
    }""")
    page.close()

    assert errors == []
    assert result == {
        "paidMatches": False,
        "freeMatches": True,
        "legacyFreeMatches": True,
        "paidDisabled": 2,
        "paidBlocked": True,
        "legacyDisabled": 0,
    }
