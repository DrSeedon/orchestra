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


def _interactive_page(browser: Browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate(
        """() => {
            window.marked = {setOptions() {}, parse(value) { return value; }};
            window.DOMPurify = {addHook() {}};
            window.usageRequests = 0;
            window.usagePending = [];
            window.api = () => {
                usageRequests += 1;
                return new Promise((resolve, reject) => {
                    usagePending.push({resolve, reject});
                });
            };
        }"""
    )
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    page.evaluate("() => initUsageBar()")
    return page


def _settle_usage(page, utilization, *, reject=False):
    page.evaluate(
        """([utilization, reject]) => {
            const pending = usagePending.shift();
            if (reject) {
                pending.reject(new DOMException('signal timed out', 'TimeoutError'));
                return;
            }
            const reset = new Date(Date.now() + 4 * 86400000).toISOString();
            pending.resolve({
                anthropic: {
                    five_hour: {utilization, resets_at: reset},
                    seven_day: {utilization: 31, resets_at: reset},
                },
                codex: {
                    primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                },
                grok: null,
                orchestra: {},
            });
        }""",
        [utilization, reject],
    )
    page.wait_for_function("() => _usageFetchPromise === null")


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


def test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm(browser):
    page = _interactive_page(browser)
    errors = []
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    _settle_usage(page, 88)

    expect(page.locator("#usage-freshness")).to_have_text("обновлено сейчас")
    expect(page.locator("#usage-freshness")).to_be_in_viewport()
    expect(page.locator("#usage-bar")).to_contain_text("88%")

    page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
    page.locator("#usage-bar").click()
    page.locator("#usage-bar").click()
    page.locator("#usage-bar").click()
    assert page.evaluate("() => usageRequests") == 2
    expect(page.locator("#usage-freshness")).to_have_text("обновление…")
    _settle_usage(page, 2)

    expect(page.locator("#usage-bar")).to_contain_text("2%")
    expect(page.locator("#usage-freshness")).to_have_text("обновлено сейчас")

    page.evaluate(
        """() => {
            window.testVisibility = 'hidden';
            Object.defineProperty(document, 'visibilityState', {
                configurable: true,
                get: () => window.testVisibility,
            });
            _usageLastSuccessAt = Date.now() - _USAGE_REFRESH_INTERVAL_MS - 1;
            _usageLastFetchStartedAt = 0;
            renderUsageBar();
            document.dispatchEvent(new Event('visibilitychange'));
        }"""
    )
    assert page.evaluate("() => usageRequests") == 2
    expect(page.locator("#usage-freshness")).to_contain_text("устарело 2 мин назад")

    page.evaluate(
        """() => {
            window.testVisibility = 'visible';
            document.dispatchEvent(new Event('visibilitychange'));
            document.dispatchEvent(new Event('visibilitychange'));
        }"""
    )
    assert page.evaluate("() => usageRequests") == 3
    _settle_usage(page, 3)
    expect(page.locator("#usage-bar")).to_contain_text("3%")

    page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
    page.locator("#usage-bar").click()
    _settle_usage(page, 0, reject=True)
    expect(page.locator("#usage-bar")).to_contain_text("3%")
    expect(page.locator("#usage-freshness")).to_contain_text("ошибка обновления")
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
