"""#51: записи type=system не должны выглядеть как ответ агента.

Проверяем подменой app.js+style.css: живой :8888 отдаёт статику из главного чекаута.
Якорь — свой узел [data-chat-system], не весь #chat: в живом чате лежит продовый текст.
"""
import pytest
from playwright.sync_api import Browser, expect, sync_playwright

from tests.test_frontend import _goto_dashboard_or_skip, _route_frontend_sources

SYSTEM_MARKER = "TASK51-SYSTEM-НЕ-ДОСТАВЛЕНО"
AGENT_MARKER = "TASK51-AGENT-обычный-ответ"


@pytest.fixture(scope="module")
def dashboard_browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:
            pytest.skip(
                f"chromium недоступен ({type(exc).__name__}); "
                "поставь его: playwright install --with-deps chromium"
            )
        yield browser
        browser.close()


def _open_chat_page(browser: Browser):
    page = browser.new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    _route_frontend_sources(page)
    _goto_dashboard_or_skip(page)
    expect(page.locator("#chat")).to_be_visible()
    page.wait_for_function("() => typeof renderSystemChatEntry === 'function'")
    page.evaluate("""() => {
        if (eventSource) { eventSource.close(); eventSource = null; }
        streamBubble = null;
        window.compactMode = false;
        document.querySelector('#chat').innerHTML = '';
    }""")
    return page


def test_system_entry_is_not_an_agent_bubble(dashboard_browser: Browser):
    page = _open_chat_page(dashboard_browser)
    try:
        loaded = page.evaluate("() => typeof renderSystemChatEntry")
        assert loaded == "function", loaded

        state = page.evaluate(
            """([systemText, agentText]) => {
                const chat = document.querySelector('#chat');
                chat.innerHTML = '';
                _renderHistory(selectedAgent || 'task51', [
                    {id: 51001, type: 'system', content: systemText,
                     ts: '2026-08-14T12:00:00+00:00'},
                    {id: 51002, type: 'text', content: agentText,
                     ts: '2026-08-14T12:00:01+00:00'},
                ]);
                const systemNode = chat.querySelector('[data-chat-system="1"]');
                const agentNode = [...chat.children].find(
                    el => el.textContent.includes(agentText)
                );
                if (!systemNode || !agentNode) {
                    return {
                        missing: !systemNode ? 'system' : 'agent',
                        childCount: chat.children.length,
                    };
                }
                const systemStyle = getComputedStyle(systemNode);
                const agentStyle = getComputedStyle(agentNode);
                return {
                    symbol: typeof renderSystemChatEntry,
                    systemClass: systemNode.className,
                    systemIcon: !!systemNode.querySelector('.codex-warning-icon'),
                    systemText: systemNode.textContent,
                    systemBorder: systemStyle.borderLeftColor,
                    systemColor: systemStyle.color,
                    systemBg: systemStyle.backgroundColor,
                    systemIsBot: systemNode.classList.contains('chat-bot'),
                    agentClass: agentNode.className,
                    agentBorder: agentStyle.borderLeftColor,
                    agentIsBot: agentNode.classList.contains('chat-bot'),
                    sameBorder: systemStyle.borderLeftColor === agentStyle.borderLeftColor,
                    sameColor: systemStyle.color === agentStyle.color,
                    navKind: systemNode.dataset.chatNavKind,
                };
            }""",
            [SYSTEM_MARKER, AGENT_MARKER],
        )

        assert state.get("missing") is None, state
        assert state["symbol"] == "function"
        assert "codex-warning" in state["systemClass"]
        assert state["systemIcon"] is True
        assert SYSTEM_MARKER in state["systemText"]
        assert state["systemIsBot"] is False
        assert state["agentIsBot"] is True
        assert state["systemBorder"] == "rgb(245, 158, 11)", state["systemBorder"]
        assert state["sameBorder"] is False, state
        assert state["sameColor"] is False, state
        assert state["navKind"] == "status"
        # Свой узел, не #chat: продовый текст в контейнере нас не касается.
        assert AGENT_MARKER not in state["systemText"]
    finally:
        page.close()
