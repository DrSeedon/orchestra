"""Frozen RED for #249 T4; frontend implementation belongs to the frontend worker."""

from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect, sync_playwright


ROOT = Path(__file__).parent.parent
_ANTIGRAVITY_BACKEND = ROOT / "app" / "backend_antigravity.py"
pytestmark = pytest.mark.skipif(
    not _ANTIGRAVITY_BACKEND.is_file(),
    reason="#249 phase 2 not implemented (no app/backend_antigravity.py); follow-up #279",
)
UTILS_JS = ROOT / "app/static/js/utils.js"
CONNECTION_JS = ROOT / "app/static/js/connection.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
STYLE_CSS = ROOT / "app/static/css/style.css"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _page(browser: Browser, antigravity, *, width: int = 1440):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.set_content('<body><div id="usage-bar"></div></body>')
    page.evaluate(
        """() => {
            window.marked = {setOptions() {}, parse(value) { return value; }};
            window.DOMPurify = {addHook() {}};
        }"""
    )
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(CONNECTION_JS))
    page.add_script_tag(path=str(USAGE_JS))
    page.add_style_tag(path=str(STYLE_CSS))
    page.evaluate(
        """antigravity => {
            const reset = new Date(Date.now() + 4 * 86400000).toISOString();
            _usageData = {
                anthropic: {
                    five_hour: {utilization: 12, resets_at: reset},
                    seven_day: {utilization: 31, resets_at: reset},
                },
                codex: {
                    primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                },
                grok: {
                    primary: {utilization: 10, window_minutes: 10080, resets_at: reset},
                },
                antigravity,
                orchestra: {total_cost_usd: 5687, agents_count: 197},
            };
            renderUsageBar();
        }""",
        antigravity,
    )
    return page


def _two_groups():
    return {
        "gemini-weekly": {
            "remaining_fraction": 0.62,
            "reset_time": "2033-05-20T04:33:20Z",
        },
        "3p-weekly": {
            "remaining_fraction": 0.17,
            "reset_time": "2033-05-23T04:33:20Z",
        },
    }


def test_t4_two_distinct_antigravity_groups_render_in_contract_order(browser):
    page = _page(browser, _two_groups())

    measured = page.evaluate(
        """() => ({
            providers: [...document.querySelectorAll('[data-usage-compact-provider]')]
                .map(node => node.dataset.usageCompactProvider),
            buckets: [...document.querySelectorAll(
                '[data-usage-compact-provider="antigravity"] [data-antigravity-bucket]'
            )].map(node => ({id: node.dataset.antigravityBucket, text: node.innerText})),
        })"""
    )

    assert measured["providers"] == ["claude", "codex", "grok", "antigravity"]
    assert [item["id"] for item in measured["buckets"]] == [
        "gemini-weekly",
        "3p-weekly",
    ]
    assert "38%" in measured["buckets"][0]["text"]
    assert "83%" in measured["buckets"][1]["text"]
    assert measured["buckets"][0]["text"] != measured["buckets"][1]["text"]

    page.locator("#usage-info-btn").hover()
    detail = page.locator('[data-usage-provider="antigravity"]')
    expect(detail).to_be_visible()
    detail_buckets = detail.locator("[data-antigravity-bucket]")
    expect(detail_buckets).to_have_count(2)
    assert detail_buckets.evaluate_all(
        "nodes => nodes.map(node => node.dataset.antigravityBucket)"
    ) == ["gemini-weekly", "3p-weekly"]
    expect(detail_buckets.nth(0)).to_contain_text("38%")
    expect(detail_buckets.nth(1)).to_contain_text("83%")
    countdowns = detail_buckets.evaluate_all(
        "nodes => nodes.map(node => node.querySelector('[data-reset-countdown]')?.textContent || '')"
    )
    assert all(countdowns)
    assert countdowns[0] != countdowns[1]
    page.close()


@pytest.mark.parametrize(
    "antigravity,missing_bucket",
    [
        ({"gemini-weekly": None, "3p-weekly": None}, "gemini-weekly"),
        ({"3p-weekly": _two_groups()["3p-weekly"]}, "gemini-weekly"),
        ({"gemini-weekly": _two_groups()["gemini-weekly"]}, "3p-weekly"),
        (None, "gemini-weekly"),
    ],
)
def test_t4_null_or_missing_group_is_explicitly_unavailable_not_zero(
    browser,
    antigravity,
    missing_bucket,
):
    page = _page(browser, antigravity)

    compact = page.locator('[data-usage-compact-provider="antigravity"]')
    expect(compact).to_be_visible()
    bucket = compact.locator(f'[data-antigravity-bucket="{missing_bucket}"]')
    expect(bucket).to_contain_text("нет данных")
    expect(bucket).not_to_contain_text("0%")

    page.locator("#usage-info-btn").hover()
    detail = page.locator(
        f'[data-usage-provider="antigravity"] '
        f'[data-antigravity-bucket="{missing_bucket}"]'
    )
    expect(detail).to_contain_text("Данные лимита недоступны")
    expect(detail).not_to_contain_text("0%")
    page.close()


def test_t4_antigravity_does_not_regress_desktop_usage_bar_overflow(browser):
    for width in (1280, 1440, 1680, 1920):
        page = _page(browser, _two_groups(), width=width)
        measured = page.evaluate(
            """() => {
                const bar = document.querySelector('#usage-bar');
                const info = document.querySelector('#usage-info-btn').getBoundingClientRect();
                const limits = document.querySelector('.usage-limits');
                return {
                    providers: [...document.querySelectorAll('[data-usage-compact-provider]')]
                        .map(node => node.dataset.usageCompactProvider),
                    infoRight: info.right,
                    infoVisible: info.width > 0 && info.height > 0,
                    viewport: innerWidth,
                    barScrollWidth: bar.scrollWidth,
                    barClientWidth: bar.clientWidth,
                    limitsWrap: getComputedStyle(limits).flexWrap,
                    text: bar.innerText,
                };
            }"""
        )
        assert measured["providers"] == ["claude", "codex", "grok", "antigravity"]
        assert measured["infoVisible"] is True
        assert measured["infoRight"] <= measured["viewport"]
        assert measured["barScrollWidth"] == measured["barClientWidth"]
        assert measured["limitsWrap"] == "wrap"
        assert "$5687" not in measured["text"]
        assert "197 agents" not in measured["text"]
        page.close()
