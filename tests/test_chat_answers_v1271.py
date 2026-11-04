"""Offline browser regression: actual chat render/history/paging/SSE and stylesheet."""
import os
import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch(executable_path=os.environ.get("CHAT_ANSWERS_CHROME") or None)
        yield instance
        instance.close()


def _boot(page):
    template = Environment(loader=FileSystemLoader(ROOT / "app/templates")).get_template("dashboard.html")
    html = template.render(is_auth_enabled=False, hide_thinking=False)
    # Load the real sources after DOMContentLoaded; start only the chat subsystem.
    # No dashboard polling, server, credentials, provider or network requests.
    html = re.sub(r"<script\b[^>]*>.*?</script>|<link\b[^>]*>", "", html, flags=re.S)
    page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html")
               if route.request.url == "http://chat-test.invalid/" else route.abort())
    page.goto("http://chat-test.invalid/")
    for css in ["design-system.css", "style.css", "vendor/tailwind.css"]:
        page.add_style_tag(path=str(STATIC / "css" / css))
    for js in ["marked.min.js", "purify.min.js"]:
        page.add_script_tag(path=str(STATIC / "css/vendor" / js))
    for js in ["i18n.js", "theme.js", "utils.js", "tool-renderers.js", "live-activity.js", "chat.js", "app.js"]:
        page.add_script_tag(path=str(STATIC / "js" / js))
    page.evaluate("""() => {
        selectedAgent = 'synthetic'; currentScope = '/synthetic';
        _chatSnapshotReady = true; scrollAfterLoad = false; _chatFollow = false;
        window.EventSource = class {
            static opened = 0;
            constructor() { EventSource.opened++; }
            close() {}
        };
        _wakeStatusRefreshFromStream = () => {};
        initChatTimeline();
        window.row = (id, type, content, extra = {}) => ({
            id, type, content, ts: '2026-11-04T10:00:00Z', ...extra,
        });
        window.deliver = entry => eventSource.onmessage({data: JSON.stringify(entry)});
    }""")


@pytest.mark.parametrize("width", [1280, 390])
def test_answers_filter_preserves_history_paging_and_sse(browser, width):
    page = browser.new_page(viewport={"width": width, "height": 800})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _boot(page)
        page.evaluate("""() => {
            _renderHistory(selectedAgent, [
                row(10, 'user_message', 'Owner question', {
                    origin: 'user', origin_detail: {senders: ['owner']},
                }),
                row(11, 'text', 'Ordinary assistant prose mentioning send_message and tools.'),
                row(12, 'user_message', 'Incoming inter-agent message', {
                    origin: 'agent', origin_detail: {senders: ['colleague']},
                }),
                row(13, 'tool', 'mcp__orchestra__send_message: {"to":"colleague","message":"Outgoing delivery"}'),
                row(14, 'tool_result', 'Orphan receipt', {tool_use_id: 'old-orphan'}),
                row(15, 'thinking', 'Private reasoning'),
                row(16, 'status', 'working on synthetic task'),
                row(17, 'system', 'Delivery failed'),
                row(18, 'assistant', 'Short assistant reply'),
            ]);
            _addLoadMoreBtn();
            window.initialNodes = [...$('#chat').children];
            connectSSE();
        }""")
        toggle = page.locator("#chat-answers-toggle")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(page.locator('[data-chat-log-id="10"]')).to_be_visible()
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")
        for id_ in [10, 12, 13, 14, 15, 16, 17]:
            expect(page.locator(f'[data-chat-log-id="{id_}"]')).to_be_hidden()
        for id_ in [11, 18]:
            expect(page.locator(f'[data-chat-log-id="{id_}"]')).to_be_visible()
        expect(page.locator("#load-more-btn")).to_be_visible()
        expect(page.locator("#chat-timeline-track .is-tool:visible")).to_have_count(0)
        expect(page.locator("#chat-timeline-track .is-user:visible")).to_have_count(0)

        # Exercise the actual lazy-page path with an offline API adapter.
        page.evaluate("""async () => {
            window.apiCalls = 0;
            api = async () => { apiCalls++; return [
                row(1, 'text', 'Older assistant answer'),
                row(2, 'user_message', 'Older incoming message'),
                row(3, 'tool', 'Bash: {"command":"offline"}'),
            ]; };
            await loadMoreLogs();
            deliver(row(19, 'user_message', 'New incoming message'));
            deliver(row(20, 'tool', 'mcp__orchestra__send_message: {"to":"peer","message":"New outgoing"}'));
            deliver(row(21, 'tool_result', 'New orphan receipt', {tool_use_id: 'new-orphan'}));
            deliver(row(22, 'thinking_stream', 'New live reasoning', {item_id:'reason'}));
            deliver(row(23, 'status', 'New live status'));
            deliver(row(24, 'stream', 'Live assistant '));
            deliver(row(25, 'stream', 'prose about tools'));
        }""")
        expect(page.locator('[data-chat-log-id="1"]')).to_be_visible()
        for id_ in [2, 3, 19, 20, 21, 22, 23]:
            expect(page.locator(f'[data-chat-log-id="{id_}"]')).to_be_hidden()
        expect(page.locator("#chat .streaming")).to_be_visible()
        expect(page.locator("#chat .streaming")).to_contain_text("Live assistant prose about tools")
        # Finalizing reuses the visible stream node; no answer is lost or duplicated.
        page.evaluate("""() => {
            window.streamNode = streamBubble;
            deliver(row(26, 'text', 'Live assistant prose about tools, complete.'));
            window.retained = [...$('#chat').children];
            _chatFollow = true;
            _chatTrimLimit = 500;
        }""")
        expect(page.locator('[data-chat-log-id="26"]')).to_be_visible()
        assert page.evaluate("streamNode === document.querySelector('[data-chat-log-id=\"26\"]')")
        # Same node identities and order on repeated toggles; no history fetch or SSE reconnect.
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")
        assert page.evaluate("""() => retained.every((node, i) => $('#chat').children[i] === node)
            && retained.length === $('#chat').children.length
            && initialNodes.filter(n => n.id !== 'load-more-btn').every(n => n.isConnected)
            && apiCalls === 1 && EventSource.opened === 1 && _chatTrimLimit === 500""")
        for id_ in [2, 3, 10, 12, 13, 14, 15, 16, 17, 19, 20, 21, 23]:
            expect(page.locator(f'[data-chat-log-id="{id_}"]')).to_be_visible()
        toggle.click()
        expect(page.locator('[data-chat-log-id="26"]')).to_be_visible()
        expect(page.locator('[data-chat-log-id="20"]')).to_be_hidden()
        box = toggle.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
        for id_ in ["compact-toggle-btn", "restart-btn", "logout-btn"]:
            control_box = page.locator(f"#{id_}").bounding_box()
            assert control_box and control_box["x"] >= 0 and control_box["x"] + control_box["width"] <= width
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if os.environ.get("CHAT_ANSWERS_SHOTS"):
            page.screenshot(path=str(Path(os.environ["CHAT_ANSWERS_SHOTS"]) / f"answers-{width}.png"))
        assert not errors, errors
    finally:
        page.close()


def test_answer_preference_reloads_and_storage_refusal_is_usable(browser):
    page = browser.new_page()
    try:
        _boot(page)
        page.locator("#chat-answers-toggle").click()
        _boot(page)
        expect(page.locator("#chat-answers-toggle")).to_have_attribute("aria-pressed", "true")
        page.evaluate("""() => {
            $('#chat-answers-toggle').remove();
            _chatAnswersOnly = false;
            Storage.prototype.getItem = () => { throw new Error('storage unavailable'); };
            Storage.prototype.setItem = () => { throw new Error('storage unavailable'); };
            _initChatAnswersToggle();
        }""")
        expect(page.locator("#chat-answers-toggle")).to_have_attribute("aria-pressed", "false")
        page.locator("#chat-answers-toggle").click()
        expect(page.locator("#chat-answers-toggle")).to_have_attribute("aria-pressed", "true")
    finally:
        page.close()


def test_filter_keeps_load_retry_controls_available(browser):
    page = browser.new_page()
    try:
        _boot(page)
        page.locator("#chat-answers-toggle").click()
        page.evaluate("_renderChatLoadState('synthetic')")
        expect(page.locator("#chat .chat-load-state")).to_be_visible()
        page.evaluate("""() => {
            window.Connection = {ownsErrors: () => false};
            _renderChatLoadState('synthetic', new Error('Synthetic load failure'));
            _showChatFor = (name, scope) => { window.retryTarget = [name, scope]; };
        }""")
        expect(page.locator("#chat .chat-load-error")).to_be_visible()
        page.locator("#chat .chat-load-error button").click()
        assert page.evaluate("retryTarget") == ["synthetic", "/synthetic"]
        page.evaluate("""_renderHistory(selectedAgent, [
            row(1, 'text', 'Recovered assistant answer'),
            row(2, 'user_message', 'Recovered incoming message'),
        ])""")
        expect(page.locator('[data-chat-log-id="1"]')).to_be_visible()
        expect(page.locator('[data-chat-log-id="2"]')).to_be_hidden()
    finally:
        page.close()
