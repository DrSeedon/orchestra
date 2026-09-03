"""#447: expose the server-owned worker headroom in the compact usage bar."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.db as db
import app.routes.system as system
from app.quota_gate import line_limit


NOW = 2_000_000_000.0
ROOT = Path(__file__).parent.parent


def _window(minutes: int, utilization: float, progress: float) -> dict:
    return {
        "id": "seven_day",
        "label": "7d",
        "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": datetime.fromtimestamp(
            NOW + minutes * 60 * (1.0 - progress), timezone.utc,
        ).isoformat(),
    }


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "quota-headroom.db")
    db.init_db()
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system.time, "time", lambda: NOW)

    async def run(observation):
        monkeypatch.setattr(system, "_quota_observation_from_cache", lambda: observation)
        return await system.quota_map()

    return run


def _observation():
    progress = 0.5
    return {
        "providers": {
            "anthropic": {
                "label": "Claude",
                "windows": [_window(10080, 30.0, progress)],
            },
            "codex": {
                "label": "Codex",
                "windows": [_window(10080, 90.0, progress)],
            },
        },
        "observed_at_by_provider": {
            "anthropic": NOW - 1,
            "codex": NOW - 1,
        },
    }


def _bucket(payload, bucket):
    return next(item for item in payload["buckets"] if item["bucket"] == bucket)


def _lane(bucket, lane):
    return next(item for item in bucket["lanes"] if item["lane"] == lane)


@pytest.mark.asyncio
async def test_quota_map_headroom_is_server_line_minus_fact(mapped):
    payload = await mapped(_observation())

    claude = _lane(_bucket(payload, "anthropic"), "claude")
    sol = _lane(_bucket(payload, "codex"), "sol")
    luna = _lane(_bucket(payload, "codex"), "luna")

    # Frozen values keep this oracle red when line_limit is shifted by a mutant.
    assert claude["headroom_pp"] == pytest.approx(55.5 - 30.0)
    assert sol["headroom_pp"] == pytest.approx(81.2858283255199 - 90.0)
    assert claude["headroom_pp"] == pytest.approx(line_limit(0.5, "claude") - 30.0)
    assert sol["headroom_pp"] == pytest.approx(line_limit(0.5, "sol") - 90.0)
    assert sol["headroom_pp"] < 0
    assert luna["headroom_pp"] is None


def test_app_js_does_not_reimplement_quota_threshold_formula():
    app_js = (ROOT / "app/static/js/app.js").read_text()
    assert "line_limit" not in app_js
    assert "tolerance_start_pp" not in app_js
    assert "curve_exponent" not in app_js


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def test_usage_bar_renders_worker_headroom_from_quota_map(browser):
    from playwright.sync_api import expect

    usage = {
        "anthropic": {
            "seven_day": {
                "utilization": 30,
                "resets_at": "2099-01-01T00:00:00+00:00",
            },
        },
        "codex": {
            "primary": {
                "window_minutes": 10080,
                "utilization": 90,
                "resets_at": "2099-01-01T00:00:00+00:00",
            },
        },
        "grok": None,
        "openrouter": None,
    }
    quota_map = {
        "buckets": [
            {
                "bucket": "anthropic",
                "data_available": True,
                "fresh": True,
                "window": {
                    "id": "seven_day",
                    "window_minutes": 10080,
                    "utilization": 30,
                    "resets_at": "2099-01-01T00:00:00+00:00",
                },
                "lanes": [{"lane": "claude", "gated": True, "headroom_pp": 25.5}],
            },
            {
                "bucket": "codex",
                "data_available": True,
                "fresh": True,
                "window": {
                    "id": "primary",
                    "window_minutes": 10080,
                    "utilization": 90,
                    "resets_at": "2099-01-01T00:00:00+00:00",
                },
                "lanes": [
                    {"lane": "sol", "label": "Sol", "gated": True, "headroom_pp": -8.7},
                    {"lane": "luna", "label": "Luna", "gated": False, "headroom_pp": None},
                ],
            },
        ],
    }

    page = browser.new_page()
    page.route(
        "http://harness.local/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<body><div id='usage-bar'></div></body>",
        ),
    )
    page.goto("http://harness.local/")
    for script in ("utils.js", "connection.js", "usage.js"):
        page.add_script_tag(path=str(ROOT / "app/static/js" / script))
    page.evaluate(
        "([usage, quota]) => { _usageData = usage; _quotaMapData = quota; renderUsageBar(); }",
        [usage, quota_map],
    )
    expect(page.locator("#usage-bar")).to_contain_text(
        "воркеры Claude: запас 25.5 п.п. до порога",
    )
    expect(page.locator("#usage-bar")).to_contain_text(
        "воркеры Sol: порог пройден, запас -8.7 п.п.",
    )
    expect(page.locator("#usage-bar")).not_to_contain_text("воркеры Luna")
    page.close()
