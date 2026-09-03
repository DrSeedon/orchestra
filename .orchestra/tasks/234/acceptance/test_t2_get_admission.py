from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[4]
UTILS_JS = ROOT / "app/static/js/utils.js"
APP_JS = ROOT / "app/static/js/app.js"


def _page(browser):
    page = browser.new_page()
    page.route(
        "http://harness.local/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<body><div id='net-fail-banner' class='hidden'></div></body>",
        ),
    )
    page.goto("http://harness.local/")
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(APP_JS))
    return page


def test_t2_only_four_gets_enter_fetch_and_timeout_starts_after_admission():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser)
        initial = page.evaluate(
            """async () => {
                window.__fetchCalls = 0;
                window.__timeoutCalls = 0;
                window.__resolvers = [];
                AbortSignal.timeout = _ms => {
                    window.__timeoutCalls++;
                    return new AbortController().signal;
                };
                window.fetch = () => {
                    window.__fetchCalls++;
                    return new Promise(resolve => window.__resolvers.push(resolve));
                };
                window.__calls = Array.from(
                    {length: 6}, (_, i) => api(`/api/models?probe=t2-${i}`)
                );
                await new Promise(resolve => setTimeout(resolve, 0));
                return {fetchCalls: window.__fetchCalls, timeoutCalls: window.__timeoutCalls};
            }"""
        )

        assert initial == {"fetchCalls": 4, "timeoutCalls": 4}, initial

        page.evaluate(
            """() => window.__resolvers.shift()({
                ok: true, json: async () => ({models: []}),
            })"""
        )
        page.wait_for_function("window.__fetchCalls === 5")
        after_release = page.evaluate(
            "() => ({fetchCalls: window.__fetchCalls, timeoutCalls: window.__timeoutCalls})"
        )
        page.close()
        browser.close()

    assert after_release == {"fetchCalls": 5, "timeoutCalls": 5}, after_release


def test_t2_caller_abort_while_queued_never_reaches_fetch():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser)
        result = page.evaluate(
            """async () => {
                let fetchCalls = 0;
                AbortSignal.timeout = _ms => new AbortController().signal;
                window.fetch = (_url, opts) => {
                    fetchCalls++;
                    return new Promise((_, reject) => {
                        opts.signal.addEventListener('abort', () => reject(opts.signal.reason));
                    });
                };
                for (let i = 0; i < 4; i++) api(`/api/models?probe=held-${i}`);
                const caller = new AbortController();
                const queued = api('/api/models?probe=queued-abort', {signal: caller.signal})
                    .then(() => 'resolved', error => error.name);
                await new Promise(resolve => setTimeout(resolve, 0));
                caller.abort();
                return {fetchCalls, outcome: await queued};
            }"""
        )
        page.close()
        browser.close()

    assert result == {"fetchCalls": 4, "outcome": "AbortError"}, result


def test_t2_failed_attempt_releases_permit_before_retry_jitter():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser)
        result = page.evaluate(
            """async () => {
                const order = [];
                let targetAttempts = 0;
                let releaseJitter = null;
                AbortSignal.timeout = _ms => new AbortController().signal;
                window.setTimeout = callback => { releaseJitter = callback; return 1; };
                window.fetch = url => {
                    order.push(url);
                    if (url.includes('target') && ++targetAttempts === 1) {
                        return Promise.reject(new TypeError('controlled retry'));
                    }
                    return new Promise(() => {});
                };
                for (let i = 0; i < 3; i++) api(`/api/models?probe=held-${i}`);
                api('/api/models?probe=target');
                for (let i = 0; i < 4; i++) await Promise.resolve();
                api('/api/models?probe=follower');
                for (let i = 0; i < 4; i++) await Promise.resolve();
                return {order, jitterPending: typeof releaseJitter === 'function'};
            }"""
        )
        page.close()
        browser.close()

    assert result["jitterPending"] is True, result
    assert any("follower" in url for url in result["order"]), result


def test_t2_non_get_bypasses_full_get_queue_and_keeps_mutation_budget():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser)
        result = page.evaluate(
            """async () => {
                const timeouts = [];
                let getCalls = 0, postCalls = 0;
                AbortSignal.timeout = ms => {
                    timeouts.push(ms);
                    return new AbortController().signal;
                };
                window.fetch = (_url, opts) => {
                    if (opts.method === 'POST') {
                        postCalls++;
                        return Promise.reject(new TypeError('controlled mutation failure'));
                    }
                    getCalls++;
                    return new Promise(() => {});
                };
                for (let i = 0; i < 4; i++) api(`/api/models?probe=held-${i}`);
                const outcome = await api('/api/mutate', {method: 'POST'})
                    .then(() => 'resolved', error => error.name);
                return {getCalls, postCalls, timeouts, outcome};
            }"""
        )
        page.close()
        browser.close()

    assert result["getCalls"] == 4, result
    assert result["postCalls"] == 1 and result["outcome"] == "TypeError", result
    assert result["timeouts"].count(5000) == 1, result
