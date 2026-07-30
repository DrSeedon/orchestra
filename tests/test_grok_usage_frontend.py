from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect, sync_playwright


ROOT = Path(__file__).parent.parent
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _page(browser: Browser, grok):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate(
        """() => {
            window.marked = {
                setOptions() {},
                parse(value) { return value; },
            };
            window.DOMPurify = { addHook() {} };
        }"""
    )
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    page.evaluate(
        """grok => {
            const reset = new Date(Date.now() + 4 * 86400000).toISOString();
            _usageData = {
                anthropic: {
                    five_hour: {utilization: 12, resets_at: reset},
                    seven_day: {utilization: 31, resets_at: reset},
                },
                codex: {
                    primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                    spark: {
                        primary: {utilization: 7, window_minutes: 10080, resets_at: reset},
                    },
                },
                grok: grok ? {
                    primary: {utilization: 10, window_minutes: 10080, resets_at: reset},
                } : null,
                orchestra: {},
            };
            renderUsageBar();
        }""",
        grok,
    )
    return page


def test_compact_bar_replaces_spark_with_grok(browser):
    page = _page(browser, True)

    expect(page.locator("#usage-bar")).to_contain_text("Grok")
    expect(page.locator("#usage-bar")).not_to_contain_text("Spark")
    expect(page.locator("#usage-bar")).to_contain_text("7d")
    page.close()


def test_usage_control_keeps_spark_and_adds_grok_third_column(browser):
    page = _page(browser, True)
    page.locator("#usage-info-btn").hover()

    expect(page.locator("[data-usage-provider]")).to_have_count(3)
    expect(page.locator('[data-usage-provider="codex"]')).to_contain_text("Spark")
    expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Grok")
    expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Использовано")
    page.close()


def test_missing_grok_data_is_visible_and_never_rendered_as_zero(browser):
    page = _page(browser, False)

    expect(page.locator("#usage-bar")).to_contain_text("Grok: нет данных")
    page.locator("#usage-info-btn").hover()
    grok = page.locator('[data-usage-provider="grok"]')
    expect(grok).to_contain_text("Данные лимита недоступны")
    expect(grok).not_to_contain_text("0%")
    page.close()


def test_usage_fetch_failure_stays_visible_and_logs_exception(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate(
        """() => {
            window.marked = {setOptions() {}, parse(value) { return value; }};
            window.DOMPurify = {addHook() {}};
            window.api = async () => {
                throw new DOMException('signal timed out', 'TimeoutError');
            };
        }"""
    )
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))

    page.evaluate("() => fetchUsage()")

    expect(page.locator("#usage-bar")).to_be_visible()
    expect(page.locator("#usage-bar")).to_contain_text("Usage unavailable")
    assert errors == ["Usage fetch failed: TimeoutError: signal timed out"]
    page.close()


def test_history_period_requires_two_points(browser):
    page = _page(browser, True)

    result = page.evaluate(
        """() => {
            const point = {
                ts: new Date().toISOString(),
                utilization: 10,
                window_minutes: 10080,
                resets_at: new Date(Date.now() + 4 * 86400000).toISOString(),
            };
            const periods = _usagePeriods({points: [point]});
            _sparkData = [{
                ts: point.ts,
                providers: {
                    grok: {
                        label: 'Grok',
                        windows: [{id: 'primary', label: '7d', ...point}],
                    },
                },
            }];
            const slot = document.createElement('div');
            document.body.appendChild(slot);
            _renderSparklines(slot, new Set(['grok']));
            return {
                periods,
                text: slot.textContent,
                svgCount: slot.querySelectorAll('svg').length,
            };
        }"""
    )

    assert result["periods"] == []
    assert result["svgCount"] == 0
    assert "Collecting data" in result["text"]
    page.close()
