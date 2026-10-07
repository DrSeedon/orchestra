"""#447: expose the server-owned worker headroom in the compact usage bar."""

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
from zoneinfo import ZoneInfo

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

    start = NOW - 0.5 * 10080 * 60
    local_start = datetime.fromtimestamp(start, timezone.utc).astimezone(ZoneInfo("Asia/Krasnoyarsk"))
    start_hour = local_start.hour + local_start.minute / 60.0 + local_start.second / 3600.0

    def cumulative_day_hours(position):
        full_days = int(position // 24.0)
        local_hour = position - full_days * 24.0
        return full_days * 16.0 + min(16.0, max(0.0, local_hour - 8.0))

    elapsed_day = cumulative_day_hours(start_hour + 84.0) - cumulative_day_hours(start_hour)
    elapsed_night = 84.0 - elapsed_day
    expected_line = (
        10.0 + 89.0 * 0.943 / 112.0 * elapsed_day
        + 89.0 * 0.057 / 56.0 * elapsed_night + 91.0 * 8.0 / 168.0
    )
    assert claude["headroom_pp"] == pytest.approx(expected_line - 30.0)
    assert sol["headroom_pp"] == pytest.approx(81.2858283255199 - 90.0)
    assert claude["headroom_pp"] == pytest.approx(line_limit(
        0.5, "claude", window_minutes=10080, window_start_at=start,
    ) - 30.0)
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
                    "lanes": [{
                        "lane": "claude", "gated": True, "headroom_pp": 25.5,
                        "release_status": "opens_in", "release_in_seconds": 3540,
                    }],
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
                    {
                        "lane": "sol", "label": "Sol", "gated": True, "headroom_pp": -8.7,
                        "release_status": "opens_in", "release_in_seconds": 3540,
                    },
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
    page.add_script_tag(content="""
        window.T = (key, values = {}) => Object.entries(values).reduce(
            (text, [name, value]) => text.replaceAll(`{${name}}`, value), key,
        );
    """)
    for script in ("utils.js", "connection.js", "usage.js"):
        page.add_script_tag(path=str(ROOT / "app/static/js" / script))
    page.evaluate(
        "([usage, quota]) => { _usageData = usage; _quotaMapData = quota; renderUsageBar(); }",
        [usage, quota_map],
    )
    values = [
        float(re.search(r"[−-]?\d+(?:\.\d+)?", text).group().replace("−", "-"))
        for text in page.locator('[data-quota-headroom="true"]').all_text_contents()
    ]
    assert values == [25.5, -8.7]

    page.evaluate("""() => {
        const lane = _quotaMapData.buckets[0].lanes[0];
        lane.headroom_pp = null;
        lane.release_status = 'opens_in';
        lane.release_in_seconds = 3540;
        renderUsageBar();
    }""")
    assert page.locator('[data-quota-headroom="true"]').count() == 1
    value = page.locator('[data-quota-headroom="true"]').inner_text()
    assert float(re.search(r"[−-]?\d+(?:\.\d+)?", value).group().replace("−", "-")) == -8.7
    page.close()


def test_usage_bar_formats_fractional_provider_utilization(browser):
    utilization = 28.999999999999996
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
    page.add_script_tag(content="""
        window.T = (key, values = {}) => Object.entries(values).reduce(
            (text, [name, value]) => text.replaceAll(`{${name}}`, value), key,
        );
    """)
    for script in ("utils.js", "connection.js", "usage.js"):
        page.add_script_tag(path=str(ROOT / "app/static/js" / script))
    page.evaluate(
        """utilization => {
            _usageData = {
                anthropic: {five_hour: {utilization, resets_at: null}},
                codex: {primary: {utilization, window_minutes: 300, resets_at: null}},
            };
            renderUsageBar();
        }""",
        utilization,
    )

    visible = page.locator("#usage-bar").inner_text()
    page.close()

    assert visible.count("29%") == 2
    assert str(utilization) not in visible


def test_usage_percent_formatter_guards_strip_without_browser():
    utils = (ROOT / "app/static/js/utils.js").read_text()
    usage = (ROOT / "app/static/js/usage.js").read_text()
    formatter = re.search(
        r"function _formatPercent\(value, digits = 0\) \{.*?\n\}",
        utils,
        re.DOTALL,
    )
    mini_bar = re.search(
        r"function _miniBar\(pct, color\) \{.*?\n\}",
        usage,
        re.DOTALL,
    )
    node = shutil.which("node")
    assert node, "Node.js is required to evaluate the dashboard percentage formatter"
    assert formatter and mini_bar, "the shared percent formatter must feed the usage strip"

    result = subprocess.run(
        [node, "-e", formatter.group() + "\n" + mini_bar.group()
         + "\nconsole.log(_miniBar(28.999999999999996, '#22c55e'));"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert "29%" in result.stdout
    assert "28.999999999999996" not in result.stdout
