from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect, sync_playwright


ROOT = Path(__file__).parent.parent
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
STYLE_CSS = ROOT / "app/static/css/style.css"
USAGE_SHOT_DIR = ROOT / "docs/tasks/356"


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
            const quotaPending = usagePending.shift();
            if (reject) {
                pending.reject(new DOMException('signal timed out', 'TimeoutError'));
                if (quotaPending) {
                    quotaPending.reject(new DOMException('signal timed out', 'TimeoutError'));
                }
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
            if (quotaPending) {
                quotaPending.resolve({buckets: []});
            }
        }""",
        [utilization, reject],
    )
    page.wait_for_function("() => _usageFetchPromise === null")


def test_compact_bar_replaces_spark_with_grok(browser):
    page = _page(browser, True)

    expect(page.locator("#usage-bar")).to_contain_text("Grok")
    expect(page.locator("#usage-bar")).to_contain_text("Codex")
    expect(page.locator("#usage-bar")).to_contain_text("Codex Spark")
    expect(page.locator("#usage-bar")).to_contain_text("7d")
    page.close()


def test_usage_bar_shows_spark_label_and_release_statuses(browser):
    page = _page(browser, True)
    page.evaluate(
        """() => {
            const now = Date.now();
            const fiveHReset = new Date(now + 1 * 3600000 + 45 * 60000).toISOString();
            const sevenDReset = new Date(now + 5 * 86400000 + 15 * 3600000 + 46 * 60000).toISOString();
            const sparkReset = new Date(now + 3 * 86400000 + 16 * 3600000 + 26 * 60000).toISOString();
            _usageData = {
                anthropic: {
                    five_hour: {id: 'cl-5h', utilization: 58, window_minutes: 300, resets_at: fiveHReset},
                    seven_day: {id: 'cl-7d', utilization: 100, window_minutes: 10080, resets_at: sevenDReset},
                },
                codex: {
                    primary: {id: 'cd-7d', utilization: 100, window_minutes: 10080, resets_at: sevenDReset},
                    spark: {
                        primary: {id: 'sp-7d', utilization: 57, window_minutes: 10080, resets_at: sparkReset},
                    },
                },
                grok: {
                    primary: {utilization: 12, window_minutes: 10080, resets_at: sevenDReset},
                },
                orchestra: {},
            };
            _quotaMapData = {
                buckets: [
                    {
                        bucket: 'anthropic',
                        data_available: true,
                        window: {id: 'cl-5h', window_minutes: 300, resets_at: fiveHReset},
                        lanes: [{gated: false, blocked: false, release_status: 'open'}],
                    },
                    {
                        bucket: 'anthropic',
                        data_available: true,
                        window: {id: 'cl-7d', window_minutes: 10080, resets_at: sevenDReset},
                        lanes: [{gated: true, blocked: false, release_status: 'opens_in', release_in_seconds: 17300}],
                    },
                    {
                        bucket: 'codex',
                        data_available: true,
                        window: {id: 'cd-7d', window_minutes: 10080, resets_at: sevenDReset},
                        lanes: [{gated: true, blocked: false, release_status: 'opens_in', release_in_seconds: 17300}],
                    },
                    {
                        bucket: 'codex_spark',
                        data_available: true,
                        window: {id: 'sp-7d', window_minutes: 10080, resets_at: sparkReset},
                        lanes: [{gated: false, blocked: false, release_status: 'open'}],
                    },
                ],
            };
            renderUsageBar();
        }"""
    )
    text = page.locator("#usage-bar").text_content() or ""
    assert "5h:" in text
    five_start = text.index("5h:")
    seven_start = text.index("7d:")
    assert "откроется" not in text[five_start:seven_start]
    assert text.count("Codex") >= 1
    assert "Codex Spark" in text
    assert "откроется через" in text
    assert "работает" in text
    provider_texts = page.locator('[data-usage-compact-provider="codex-spark"]').all_text_contents()
    assert len(provider_texts) == 1
    assert "Codex Spark" in provider_texts[0]
    assert "7d:" in provider_texts[0]
    page.close()


def test_usage_bar_renders_each_provider_on_own_line(browser):
    USAGE_SHOT_DIR.mkdir(parents=True, exist_ok=True)

    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate("() => { window.marked = {setOptions() {}, parse(value) { return value; } }; window.DOMPurify = { addHook() {} }; }")
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(USAGE_JS))
    page.add_style_tag(path=str(STYLE_CSS))

    usage = {
        "anthropic": {
            "five_hour": {"utilization": 38, "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
            "seven_day": {"utilization": 60, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
        },
        "codex": {
            "primary": {"utilization": 40, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
            "spark": {"primary": {"utilization": 57, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"}},
        },
        "grok": {"primary": {"utilization": 7, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"}},
        "orchestra": {},
    }
    quota_map = {
        "buckets": [
            {
                "bucket": "anthropic",
                "data_available": True,
                "window": {"id": "cl-5h", "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
                "lanes": [{"gated": False, "blocked": False, "release_status": "open"}],
            },
            {
                "bucket": "anthropic",
                "data_available": True,
                "window": {"id": "cl-7d", "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
                "lanes": [{"gated": True, "blocked": False, "release_status": "opens_in", "release_in_seconds": 900}],
            },
            {
                "bucket": "codex",
                "data_available": True,
                "window": {"id": "cd-7d", "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
                "lanes": [{"gated": True, "blocked": False, "release_status": "opens_in", "release_in_seconds": 900}],
            },
            {
                "bucket": "codex_spark",
                "data_available": True,
                "window": {"id": "sp-7d", "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
                "lanes": [{"gated": False, "blocked": False, "release_status": "open"}],
            },
            {
                "bucket": "grok",
                "data_available": True,
                "window": {"id": "gk-7d", "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
                "lanes": [{"gated": False, "blocked": False, "release_status": "open"}],
            },
        ],
    }
    page.evaluate(
        """([usage, quotaMap]) => {
            const now = Date.now();
            quotaMap.buckets[0].window.resets_at = new Date(now + 3600000).toISOString();
            quotaMap.buckets[1].window.resets_at = new Date(now + 5 * 86400000).toISOString();
            for (const item of [quotaMap.buckets[2], quotaMap.buckets[3], quotaMap.buckets[4]]) {
                item.window.resets_at = new Date(now + 3 * 86400000).toISOString();
            }
            usage.anthropic.five_hour.resets_at = new Date(now + 3600000).toISOString();
            usage.anthropic.seven_day.resets_at = new Date(now + 5 * 86400000).toISOString();
            usage.codex.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
            usage.codex.spark.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
            usage.grok.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
            window._usageDataFromApi = usage;
            window._quotaMapDataFromApi = quotaMap;
            window.api = (path) => path.includes('quota-map') ? Promise.resolve(_quotaMapDataFromApi) : Promise.resolve(_usageDataFromApi);
            initUsageBar();
        }""",
        [usage, quota_map],
    )

    expect(page.locator("#usage-bar")).to_contain_text("5h:")
    expect(page.locator("#usage-bar")).to_contain_text("7d:")
    expect(page.locator("#usage-bar")).to_contain_text("Codex Spark")
    expect(page.locator("[data-usage-compact-provider='claude']")).to_have_count(1)
    expect(page.locator("[data-usage-compact-provider='codex']")).to_have_count(1)
    expect(page.locator("[data-usage-compact-provider='codex-spark']")).to_have_count(1)
    expect(page.locator("[data-usage-compact-provider='grok']")).to_have_count(1)
    expect(page.locator("[data-usage-compact-provider='claude']")).to_contain_text("Claude")
    expect(page.locator("[data-usage-compact-provider='codex']")).to_contain_text("Codex")
    expect(page.locator("[data-usage-compact-provider='codex-spark']")).to_contain_text("Codex Spark")
    expect(page.locator("[data-usage-compact-provider='grok']")).to_contain_text("Grok")
    bounds = page.locator("#usage-bar").bounding_box()
    assert bounds is not None
    assert bounds["height"] <= 120
    page.locator("#usage-bar").screenshot(path=str(USAGE_SHOT_DIR / "usage-bar-provider-lines.png"))
    page.close()


def test_usage_controls_stay_visible_across_desktop_widths(browser):
    for width in (1280, 1440, 1680, 1920):
        page = _page(browser, True)
        page.set_viewport_size({"width": width, "height": 900})
        page.add_style_tag(path=str(STYLE_CSS))
        page.evaluate(
            """() => {
                _usageData.orchestra = {total_cost_usd: 5687, agents_count: 197};
                renderUsageBar();
            }"""
        )
        measured = page.evaluate(
            """() => {
                const bar = document.querySelector('#usage-bar');
                const info = document.querySelector('#usage-info-btn').getBoundingClientRect();
                return {
                    infoRight: info.right,
                    viewport: innerWidth,
                    scrollWidth: bar.scrollWidth,
                    clientWidth: bar.clientWidth,
                    providers: [...document.querySelectorAll('[data-usage-compact-provider]')]
                        .map(node => node.dataset.usageCompactProvider),
                };
            }"""
        )
        assert measured["providers"] == ["claude", "codex", "codex-spark", "grok"]
        assert measured["infoRight"] <= measured["viewport"]
        assert measured["scrollWidth"] == measured["clientWidth"]
        expect(page.locator("#usage-bar")).not_to_contain_text("$5687")
        expect(page.locator("#usage-bar")).not_to_contain_text("197 agents")
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

    expect(page.locator("#usage-bar")).to_contain_text("Grok")
    expect(page.locator("#usage-bar")).to_contain_text("нет данных")
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
    assert page.evaluate("() => usageRequests") == 4
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
    assert page.evaluate("() => usageRequests") == 4
    expect(page.locator("#usage-freshness")).to_contain_text("устарело 2 мин назад")

    page.evaluate(
        """() => {
            window.testVisibility = 'visible';
            document.dispatchEvent(new Event('visibilitychange'));
            document.dispatchEvent(new Event('visibilitychange'));
        }"""
    )
    assert page.evaluate("() => usageRequests") == 6
    _settle_usage(page, 3)
    expect(page.locator("#usage-bar")).to_contain_text("3%")

    page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
    page.locator("#usage-bar").click()
    _settle_usage(page, 0, reject=True)
    expect(page.locator("#usage-bar")).to_contain_text("Usage unavailable")
    expect(page.locator("#usage-freshness")).to_have_count(0)
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
    # Заглушка теперь называет ПРИЧИНУ вместо «Collecting data...»: одной точки мало,
    # а сбор при этом идёт — раньше этот случай был неотличим от «данных нет вообще».
    assert "Мало точек" in result["text"]
    page.close()
