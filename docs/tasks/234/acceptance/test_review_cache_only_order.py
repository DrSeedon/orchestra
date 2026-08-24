from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[4]
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
APP_JS = ROOT / "app/static/js/app.js"


def _page(browser, *, with_usage=True):
    page = browser.new_page()
    page.route(
        "http://harness.local/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=(
                "<body><div id='net-fail-banner' class='hidden'></div>"
                "<div id='usage-bar'></div><div id='quota-lines'></div></body>"
            ),
        ),
    )
    page.goto("http://harness.local/")
    page.add_script_tag(path=str(UTILS_JS))
    if with_usage:
        page.add_script_tag(path=str(USAGE_JS))
    page.add_script_tag(path=str(APP_JS))
    return page


def test_review_quota_map_waits_for_usage_refresh_owner():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser)
        result = page.evaluate(
            """async () => {
                const order = [];
                let releaseUsage;
                const usageGate = new Promise(resolve => { releaseUsage = resolve; });
                api = async url => {
                    if (url === '/api/usage') {
                        order.push('usage:start');
                        await usageGate;
                        order.push('usage:end');
                        return {anthropic: {}, codex: {}, grok: null, openrouter: null,
                                orchestra: {}, voice_cost_usd: 0, subscription_cost: ''};
                    }
                    if (url === '/api/usage/quota-map') {
                        order.push('quota');
                        return {data_available: false, error: 'controlled-no-data'};
                    }
                    throw new Error(`unexpected URL ${url}`);
                };
                const usage = fetchUsage();
                const lines = fetchQuotaLines();
                for (let i = 0; i < 4; i++) await Promise.resolve();
                const beforeUsageSettled = [...order];
                releaseUsage();
                await Promise.all([usage, lines]);
                return {beforeUsageSettled, finalOrder: order};
            }"""
        )
        page.close()
        browser.close()

    assert result["beforeUsageSettled"] == ["usage:start"], result
    assert result["finalOrder"] == ["usage:start", "usage:end", "quota"], result


def test_review_stale_unknown_lane_never_summarizes_as_working():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser, with_usage=False)
        result = page.evaluate(
            """() => {
                _quotaLinesError = '';
                _quotaLinesData = {
                    rule: {hard_stop_pct: 99, tolerance_start_pp: 10, tolerance_end_pp: 1},
                    buckets: [{
                        bucket: 'codex', label: 'Codex', fresh: false, data_available: true,
                        window: {id:'primary', utilization:25, progress:0.5,
                                 window_minutes:300, resets_at:'2033-05-24T03:33:20+00:00'},
                        limit_pct: 59.5, tolerance_pp: 5.5, reference_windows: [],
                        trace: {points: []}, models: [],
                        lanes: [{lane:'sol', label:'Sol', gated:true, blocked:false,
                                 release_status:'no_data', release_in_seconds:null,
                                 reason:'observation is stale', models:[]}],
                    }],
                    outside_policy: [],
                };
                renderQuotaLines();
                return {
                    verdict: document.querySelector("[data-ql-panel='all'] [data-ql-verdict]")?.textContent || '',
                    badge: document.querySelector("[data-ql-panel='all'] [data-ql-lane='sol']")?.textContent || '',
                };
            }"""
        )
        page.close()
        browser.close()

    assert "нет данных" in result["verdict"], result
    assert "работают" not in result["verdict"], result
    assert "нет данных" in result["badge"], result
