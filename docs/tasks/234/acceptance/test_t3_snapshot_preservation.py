from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[4]
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
APP_JS = ROOT / "app/static/js/app.js"


def test_t3_failed_usage_keeps_last_good_snapshot_visible():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "http://harness.local/**",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=(
                    "<body><div id='net-fail-banner' class='hidden'></div>"
                    "<div id='usage-bar'></div></body>"
                ),
            ),
        )
        page.goto("http://harness.local/")
        page.add_script_tag(path=str(UTILS_JS))
        page.add_script_tag(path=str(USAGE_JS))
        page.add_script_tag(path=str(APP_JS))

        result = page.evaluate(
            """async () => {
                const lastGood = {
                    anthropic: {
                        five_hour: {utilization: 41, resets_at: null},
                        seven_day: {utilization: 62, resets_at: null},
                    },
                    codex: {}, grok: null, openrouter: null,
                    orchestra: {}, voice_cost_usd: 0, subscription_cost: '',
                };
                snapshotSave('usage', lastGood);
                _usageData = null; _usageError = false; _quotaMapData = null;
                _restoreUsageSnapshot();
                api = url => {
                    if (url === '/api/usage') return Promise.reject(new TypeError('controlled loss'));
                    if (url === '/api/usage/quota-map') {
                        return Promise.resolve({data_available: false, error: 'controlled-no-data'});
                    }
                    return Promise.reject(new Error(`unexpected URL ${url}`));
                };
                await fetchUsage();
                const saved = snapshotLoad('usage');
                return {
                    usageText: document.querySelector('#usage-bar')?.innerText || '',
                    usageError: _usageError,
                    memoryUtilization: _usageData?.anthropic?.five_hour?.utilization ?? null,
                    savedUtilization: saved?.data?.anthropic?.five_hour?.utilization ?? null,
                };
            }"""
        )
        page.close()
        browser.close()

    assert result["usageError"] is True
    assert result["memoryUtilization"] == 41, result
    assert result["savedUtilization"] == 41, result
    assert "5h" in result["usageText"] and "Usage unavailable" not in result["usageText"], result


def test_t3_failed_usage_without_snapshot_stays_explicit_and_does_not_save_null():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "http://harness.local/**",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body=(
                    "<body><div id='net-fail-banner' class='hidden'></div>"
                    "<div id='usage-bar'></div></body>"
                ),
            ),
        )
        page.goto("http://harness.local/")
        page.add_script_tag(path=str(UTILS_JS))
        page.add_script_tag(path=str(USAGE_JS))
        page.add_script_tag(path=str(APP_JS))
        result = page.evaluate(
            """async () => {
                localStorage.removeItem('orchestra_snapshot:usage');
                _usageData = null; _usageError = false; _quotaMapData = null;
                api = url => url === '/api/usage'
                    ? Promise.reject(new TypeError('controlled loss'))
                    : Promise.resolve({data_available: false, error: 'controlled-no-data'});
                await fetchUsage();
                return {
                    usageText: document.querySelector('#usage-bar')?.innerText || '',
                    saved: snapshotLoad('usage'),
                };
            }"""
        )
        page.close()
        browser.close()

    assert "Usage unavailable" in result["usageText"], result
    assert result["saved"] is None, result
