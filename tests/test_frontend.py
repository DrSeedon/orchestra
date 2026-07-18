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
        const expired = new Date(Date.now() - 31 * 60000).toISOString();
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
    assert states["expired"]["text"] == "🧊?"
    assert states["expired"]["tier"] == "unknown"
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
