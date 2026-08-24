import asyncio
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

import app.db as db
import app.routes.system as system


ROOT = Path(__file__).resolve().parents[4]
UTILS_JS = ROOT / "app/static/js/utils.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
APP_JS = ROOT / "app/static/js/app.js"
NOW = 2_000_000_000.0


def _window(provider: str):
    return {
        "id": "seven_day" if provider == "anthropic" else "primary",
        "label": "7d",
        "window_minutes": 10080,
        "utilization": 25.0,
        "resets_at": "2033-05-24T03:33:20+00:00",
    }


def test_t1_quota_map_is_cache_only(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "quota-map-cache-only.db")
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system.time, "time", lambda: NOW)
    monkeypatch.setattr(
        system,
        "_quota_observation_from_cache",
        lambda: {
            "providers": {
                provider: {"label": provider, "windows": [_window(provider)]}
                for provider in ("anthropic", "codex", "codex_spark")
            },
            "observed_at_by_provider": {
                provider: NOW - 10
                for provider in ("anthropic", "codex", "codex_spark")
            },
        },
    )

    async def forbidden_refresh(*_args, **_kwargs):
        raise AssertionError("quota-map must not refresh providers")

    monkeypatch.setattr(system, "_get_usage_data", forbidden_refresh)
    payload = asyncio.run(system.build_quota_map())

    assert payload["generated_at"]
    assert payload["rule"]
    assert {bucket["bucket"] for bucket in payload["buckets"]} >= {
        "anthropic", "codex", "codex_spark",
    }


def test_t1_back_to_back_consumers_share_one_quota_request():
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
                    "<div id='usage-bar'></div><div id='quota-lines'></div></body>"
                ),
            ),
        )
        page.goto("http://harness.local/")
        page.add_script_tag(path=str(UTILS_JS))
        page.add_script_tag(path=str(USAGE_JS))
        page.add_script_tag(path=str(APP_JS))

        result = page.evaluate(
            """async () => {
                let releaseQuota;
                const quotaGate = new Promise(resolve => { releaseQuota = resolve; });
                let quotaCalls = 0;
                api = async url => {
                    if (url === '/api/usage/quota-map') {
                        quotaCalls++;
                        await quotaGate;
                        return {data_available: false, error: 'controlled-no-data'};
                    }
                    if (url === '/api/usage') {
                        return {anthropic: {}, codex: {}, grok: null, openrouter: null,
                                orchestra: {}, voice_cost_usd: 0, subscription_cost: ''};
                    }
                    throw new Error(`unexpected URL ${url}`);
                };
                const usage = fetchUsage();
                const lines = fetchQuotaLines();
                await Promise.resolve();
                releaseQuota();
                await Promise.all([usage, lines]);
                const quotaCallsAfterFirstWave = quotaCalls;
                await fetchQuotaLines();
                return {quotaCallsAfterFirstWave, quotaCallsAfterSecondWave: quotaCalls};
            }"""
        )
        page.close()
        browser.close()

    assert result["quotaCallsAfterFirstWave"] == 1, result
    assert result["quotaCallsAfterSecondWave"] == 2, result
