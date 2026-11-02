"""V-1205: model picker popover. Real renderer + stylesheet, synthetic catalog, no server."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
SOURCE = (STATIC / "js" / "app.js").read_text()
# SCREENSHOT_DIR is an opt-in for manual evidence; the assertions never depend on it.
SHOTS = os.environ.get("MODEL_PICKER_SHOTS")

CATALOG = [
    {"id": "claude-opus-5-5[1m]", "name": "Opus 5.5 (1M)", "runtime": "claude", "provider": "anthropic", "context_length": 1000000},
    {"id": "claude-sonnet-5-5[1m]", "name": "Sonnet 5.5 (1M)", "runtime": "claude", "provider": "anthropic", "context_length": 1000000},
    {"id": "claude-haiku-5-5", "name": "Haiku 5.5", "runtime": "claude", "provider": "anthropic", "context_length": 200000},
    {"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol", "runtime": "codex", "provider": "openai", "context_length": 258400},
    {"id": "gpt-6-luna", "name": "GPT-6 Luna", "runtime": "codex", "provider": "openai", "context_length": 258400},
    {"id": "grok-4.6", "name": "Grok 4.6", "runtime": "grok", "provider": "x-ai", "context_length": 500000},
    {"id": "hub-claude-sonnet-5-5", "name": "Hub: Sonnet 5.5", "runtime": "hub", "provider": "multicode"},
    {"id": "GigaChat-2-Max", "name": "GigaChat 2 Max", "runtime": "harness", "provider": "gigachat", "context_length": 128000},
    {"id": "GigaChat-3-Pro", "name": "GigaChat 3 Pro", "runtime": "harness", "provider": "gigachat", "context_length": 128000},
] + [
    {"id": f"filler-{i}", "name": f"Filler model {i}", "runtime": "codex", "provider": "openai"} for i in range(30)
]


def _picker_source() -> str:
    start = SOURCE.index("function _isModelChoiceHidden(")
    end = SOURCE.index("function updateAgentInfo(")
    reason = SOURCE[SOURCE.index("function _modelReasonForSelection("):SOURCE.index("function _modelReasonBadge(")]
    return reason + SOURCE[start:end]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(
            headless=True, executable_path=os.environ.get("MODEL_PICKER_CHROME") or None,
        )
        yield instance
        instance.close()


def _open(browser: Browser, width: int, height: int, current: str, anchor_style: str = ""):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_content(
        "<body style='margin:0;background:#0a0e17;color:#e2e8f0'>"
        f"<div style='padding:12px 8px;{anchor_style}'><span id='ai-model'></span>"
        "<span id='anchor' tabindex='0' style='cursor:pointer'>⇄</span></div></body>"
    )
    page.add_style_tag(path=str(STATIC / "css" / "design-system.css"))
    page.add_style_tag(path=str(STATIC / "css" / "style.css"))
    page.add_script_tag(path=str(STATIC / "js" / "theme.js"))
    page.evaluate("""models => {
        window._MODELS = models.map(m => ({...m, label: m.name}));
        window.currentScope = 'synthetic';
        window.$ = s => document.querySelector(s);
        window.T = t => t;
        window._ensureModels = async () => {};
        window.requests = [];
        window.api = async (url, options) => { window.requests.push({url, body: JSON.parse(options.body)}); return {}; };
        window._showHistoryTransfer = () => {};
        window.loadSessions = () => {};
    }""", CATALOG)
    page.add_script_tag(content=_picker_source())
    page.evaluate(f"_showModelPicker('w', {current!r}, $('#anchor'))")
    page.wait_for_selector("#model-picker-dd")
    return page


def _shot(page, name):
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))


def _box_inside_viewport(page):
    return page.evaluate("""() => {
        const r = document.querySelector('#model-picker-dd').getBoundingClientRect();
        return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;
    }""")


def _names(page):
    return page.eval_on_selector_all("#model-picker-dd .model-picker-name", "els => els.map(e => e.textContent)")


@pytest.mark.parametrize("width,height,label", [(1280, 720, "desktop"), (360, 640, "narrow")])
def test_popover_is_bounded_scrolls_and_hides_gigachat(browser, width, height, label):
    page = _open(browser, width, height, "claude-opus-5-5[1m]")
    try:
        assert _box_inside_viewport(page)
        scroll = page.evaluate("""() => { const l = document.querySelector('.model-picker-list');
            return [l.scrollHeight > l.clientHeight, getComputedStyle(l).overflowY]; }""")
        assert scroll == [True, "auto"]
        names = _names(page)
        assert names[0] == "Opus 5.5 (1M)"  # current model is shown first, as a label
        assert not any("GigaChat" in n for n in names)
        assert names.count("Opus 5.5 (1M)") == 1  # and is not offered as a target
        headers = page.eval_on_selector_all(".model-picker-group", "els => els.map(e => e.textContent)")
        assert headers[:3] == ["Claude", "Codex", "Grok"]
        _shot(page, f"picker-{label}")
    finally:
        page.close()


def test_current_gigachat_model_is_still_shown_but_not_offered(browser):
    page = _open(browser, 1280, 720, "GigaChat-2-Max")
    try:
        names = _names(page)
        assert names[0] == "GigaChat 2 Max"
        assert not any("GigaChat" in n for n in names[1:])
        assert page.locator(".model-picker-current").inner_text().count("GigaChat 2 Max") == 1
        _shot(page, "picker-current-gigachat")
    finally:
        page.close()


def test_unknown_current_model_falls_back_to_its_id(browser):
    page = _open(browser, 1280, 720, "legacy-model-x")
    try:
        assert _names(page)[0] == "legacy-model-x"
    finally:
        page.close()


def test_anchor_near_bottom_opens_upwards_and_stays_in_viewport(browser):
    page = _open(browser, 360, 640, "claude-opus-5-5[1m]", anchor_style="position:fixed;bottom:10px;right:4px")
    try:
        assert _box_inside_viewport(page)
        _shot(page, "picker-bottom-narrow")
    finally:
        page.close()


def test_escape_closes_and_returns_focus(browser):
    page = _open(browser, 1280, 720, "claude-opus-5-5[1m]")
    try:
        page.keyboard.press("Escape")
        assert page.locator("#model-picker-dd").count() == 0
        assert page.evaluate("document.activeElement.id") == "anchor"
    finally:
        page.close()


def test_click_outside_closes_without_selecting(browser):
    page = _open(browser, 1280, 720, "claude-opus-5-5[1m]")
    try:
        page.mouse.click(900, 600)
        assert page.locator("#model-picker-dd").count() == 0
        assert page.evaluate("window.requests") == []
    finally:
        page.close()


def test_arrow_keys_move_focus_and_enter_selects(browser):
    page = _open(browser, 1280, 720, "claude-opus-5-5[1m]")
    try:
        first = page.evaluate("document.activeElement.title")
        page.keyboard.press("ArrowDown")
        second = page.evaluate("document.activeElement.title")
        assert first == "claude-sonnet-5-5[1m]" and second == "claude-haiku-5-5"
        page.keyboard.press("ArrowUp")
        page.keyboard.press("ArrowUp")  # wraps to the last row
        assert page.evaluate("document.activeElement.title") == "hub-claude-sonnet-5-5"
        page.keyboard.press("Home")
        page.keyboard.press("Enter")
        assert page.evaluate("window.requests") == [
            {"url": "/api/sessions/w/change-model", "body": {"model": "claude-sonnet-5-5[1m]", "scope": "synthetic"}},
        ]
        assert page.locator("#model-picker-dd").count() == 0
    finally:
        page.close()


def test_reason_prompt_still_required_for_hub_claude(browser):
    page = _open(browser, 1280, 720, "claude-opus-5-5[1m]")
    try:
        page.evaluate("window.prompt = () => null")
        page.locator("button[title='hub-claude-sonnet-5-5']").click()
        assert page.evaluate("window.requests") == []
    finally:
        page.close()


def test_new_orchestrator_selector_skips_gigachat_but_keeps_catalog():
    assert "if (_isModelChoiceHidden(m)) continue;" in SOURCE.split("function _renderModels(", 1)[1].split("async function _loadModelsNow", 1)[0]
    assert "_MODELS = models.map" in SOURCE.split("function _renderModels(", 1)[1][:200]
