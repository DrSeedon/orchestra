"""Playwright smoke tests for Orchestra dashboard.

Requires: Orchestra running on localhost:8888 (no auth).
Run: pytest tests/test_frontend.py -v
"""

from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

BASE = "http://localhost:8888"


@pytest.fixture(scope="module")
def dashboard_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def dashboard_page(dashboard_browser: Browser):
    page = dashboard_browser.new_page()
    resp = page.goto(BASE, wait_until="domcontentloaded")
    assert resp.status == 200
    expect(page.locator("#agent-list")).to_be_visible()
    yield page
    page.close()


def test_dashboard_loads(dashboard_page: Page):
    expect(dashboard_page).to_have_title("🎼 Orchestra")


def test_sidebar_agents_visible(dashboard_page: Page):
    agent_list = dashboard_page.locator("#agent-list")
    expect(agent_list).to_be_visible()


def test_chat_input_exists(dashboard_page: Page):
    chat_input = dashboard_page.locator("#chat-input")
    expect(chat_input).to_be_visible()
    expect(chat_input).to_be_enabled()


def test_send_button_exists(dashboard_page: Page):
    send_btn = dashboard_page.locator("#send-btn")
    expect(send_btn).to_be_visible()
    expect(send_btn).to_have_text("Send")


def test_usage_bar_visible(dashboard_page: Page):
    usage_bar = dashboard_page.locator("#usage-bar")
    expect(usage_bar).to_be_attached()


def test_header_has_orch_tabs(dashboard_page: Page):
    tabs = dashboard_page.locator("#orch-tabs")
    expect(tabs).to_be_visible()


def test_left_panel_has_tabs(dashboard_page: Page):
    files_tab = dashboard_page.locator('[data-left-tab="files"]')
    tasks_tab = dashboard_page.locator('[data-left-tab="tasks"]')
    jobs_tab = dashboard_page.locator('[data-left-tab="jobs"]')
    expect(files_tab).to_be_visible()
    expect(tasks_tab).to_be_visible()
    expect(jobs_tab).to_be_visible()


def test_agent_info_panel_exists(dashboard_page: Page):
    info = dashboard_page.locator("#agent-info")
    expect(info).to_be_visible()


def test_no_js_errors(dashboard_browser: Browser):
    errors = []
    page = dashboard_browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="domcontentloaded")
    expect(page.locator("#agent-list")).to_be_visible()
    page.wait_for_timeout(2000)
    page.close()
    assert len(errors) == 0, f"JS errors on page: {errors}"


def _load_cache_pill_code(page: Page):
    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
    block = "function _cachePillState" + source.split(
        "function _cachePillState", 1,
    )[1].split("// Client-side countdown", 1)[0]
    page.set_content("<body></body>")
    page.add_script_tag(content=block)


def test_codex_cache_pill_is_approximate_and_expires_to_unknown(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    _load_cache_pill_code(page)
    states = page.evaluate("""() => {
        const snapshot = (pill) => pill && ({
            text: pill.textContent,
            tier: pill.dataset.tier,
            title: pill.title,
            approximate: pill.dataset.cacheApproximate,
        });
        const recent = new Date(Date.now() - 5 * 60000).toISOString();
        const expired = new Date(Date.now() - 37 * 60000).toISOString();
        return {
            running: snapshot(_cachePill({
                status: 'running',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            recent: snapshot(_cachePill({
                status: 'idle',
                last_turn_ts: recent,
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            expired: snapshot(_cachePill({
                status: 'idle',
                last_turn_ts: expired,
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            })),
            invalidTtl: _cachePill({
                status: 'idle',
                last_turn_ts: recent,
                cache_ttl_seconds: 0,
                cache_ttl_approximate: true,
            }),
            missingTurn: _cachePill({
                status: 'idle',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            }),
            malformedTurn: _cachePill({
                status: 'idle',
                last_turn_ts: 'not-a-date',
                cache_ttl_seconds: 1800,
                cache_ttl_approximate: true,
            }),
        };
    }""")
    page.close()

    assert states["running"]["text"] == "🔥≈"
    assert states["recent"]["text"].startswith("🔥≈")
    assert states["recent"]["approximate"] == "1"
    assert states["expired"]["text"] == "🧊? +7m"
    assert states["expired"]["tier"] == "unknown"
    assert "7m past" in states["expired"]["title"]
    assert "not guaranteed" in states["expired"]["title"]
    assert states["invalidTtl"] is None
    assert states["missingTurn"] is None
    assert states["malformedTurn"] is None


def test_claude_cache_pill_keeps_exact_thresholds(dashboard_browser: Browser):
    page = dashboard_browser.new_page()
    _load_cache_pill_code(page)
    states = page.evaluate("""() => {
        const stateAt = (minutesAgo) => {
            const pill = _cachePill({
                status: 'idle',
                last_turn_ts: new Date(Date.now() - minutesAgo * 60000).toISOString(),
                cache_ttl_seconds: 3600,
                cache_ttl_approximate: false,
            });
            return {text: pill.textContent, tier: pill.dataset.tier, title: pill.title};
        };
        return {
            hot: stateAt(20),
            warm: stateAt(45),
            cooling: stateAt(49),
            cold: stateAt(61),
        };
    }""")
    page.close()

    assert states["hot"]["tier"] == "hot"
    assert states["warm"]["tier"] == "warm"
    assert states["cooling"]["tier"] == "cooling"
    assert states["cold"] == {
        "text": "🧊",
        "tier": "cold",
        "title": "Cache cold — next turn ~20× дороже",
    }


def _open_tool_fixture_page(browser: Browser) -> Page:
    page = browser.new_page()
    page.goto(BASE, wait_until="domcontentloaded")
    expect(page.locator("#chat")).to_be_visible()
    page.wait_for_function(
        "() => typeof selectedAgent !== 'undefined' && selectedAgent !== null"
    )
    page.evaluate("""() => {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        window.compactMode = false;
        document.querySelector('#chat').innerHTML = '';
    }""")
    return page


def test_codex_successful_mcp_startup_status_is_hidden(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry('status', 'codex mcp orchestra: starting');
        addChatEntry('status', 'codex mcp orchestra: ready');
    }""")

    expect(page.locator("#chat").locator("text=codex mcp")).to_have_count(0)
    page.close()


def test_codex_web_search_renders_queries_without_transport_json(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    page.evaluate("""() => {
        addChatEntry(
            'tool',
            'WebSearch: {"query":"","action":null,"_codex_item_id":"web-1"}',
            null,
            null,
            {tool_use_id: 'web-1'}
        );
        addChatEntry(
            'tool_result',
            JSON.stringify({
                query: 'AOSP official documentation',
                action: {
                    type: 'search',
                    query: null,
                    queries: [
                        'site:source.android.com AOSP CDD official',
                        'site:source.android.com CTS compatibility official',
                        'site:developer.android.com Play Integrity official',
                    ],
                },
                status: 'completed',
            }),
            null,
            null,
            {tool_use_id: 'web-1'}
        );
    }""")

    card = page.locator("#chat .codex-tool-card")
    expect(card).to_have_count(1)
    expect(card.locator(".codex-tool-title")).to_have_text("Web search")
    expect(card.locator(".codex-search-query")).to_have_count(3)
    expect(card.locator(".codex-tool-state")).to_have_text("done")
    text = card.inner_text()
    assert '"action"' not in text
    assert '"queries"' not in text
    page.close()


def test_codex_spawn_worker_renders_task_model_and_completion(
    dashboard_browser: Browser,
):
    page = _open_tool_fixture_page(dashboard_browser)
    payload = {
        "name": "mobile-os-strategy",
        "role": "full-cycle",
        "model": "gpt-5.6-sol",
        "task": "Research an AOSP-first product strategy.",
        "description": "Mobile OS strategy",
        "system_prompt": "Detailed instructions. " * 200,
        "_codex_item_id": "spawn-1",
    }
    page.evaluate(
        """([payload]) => {
            addChatEntry(
                'tool',
                `mcp__orchestra__spawn_worker: ${JSON.stringify(payload)}`,
                null,
                null,
                {tool_use_id: 'spawn-1'}
            );
            addChatEntry(
                'tool_result',
                "Worker 'mobile-os-strategy' spawned. Model: gpt-5.6-sol. Task sent.",
                null,
                null,
                {tool_use_id: 'spawn-1'}
            );
        }""",
        [payload],
    )

    card = page.locator("#chat .codex-tool-card")
    expect(card).to_have_count(1)
    expect(card.locator(".codex-tool-title")).to_have_text(
        "mobile-os-strategy spawned"
    )
    expect(card.locator(".codex-tool-state")).to_have_text("done")
    expect(card).to_contain_text("GPT-5.6 Sol")
    expect(card).to_contain_text("Research an AOSP-first product strategy.")
    assert '"system_prompt"' not in card.inner_text()
    page.close()
