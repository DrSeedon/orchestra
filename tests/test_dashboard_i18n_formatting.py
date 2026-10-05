from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from app.quota_gate import LANE_LABELS

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _formatting_page(browser, language):
    context = browser.new_context()
    context.add_init_script(f"localStorage.setItem('orch_lang', '{language}')")
    page = context.new_page()
    page.route("http://harness.local/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<body></body>"))
    page.goto("http://harness.local/")
    page.add_script_tag(path=str(ROOT / "app/static/js/utils.js"))
    page.add_script_tag(path=str(ROOT / "app/static/js/i18n.js"))
    page.add_script_tag(path=str(ROOT / "app/static/js/usage.js"))
    page.add_script_tag(path=str(ROOT / "app/static/js/analytics.js"))
    return context, page


def test_dashboard_numbers_and_dates_follow_the_selected_language(browser):
    assert LANE_LABELS["claude"] == "Claude workers"
    values = {}
    for language in ("en", "ru"):
        context, page = _formatting_page(browser, language)
        try:
            values[language] = page.evaluate("""() => ({
                money: _analyticsMoney(212.8),
                number: _analyticsNumber(1234.5),
                analyticsDate: _analyticsDateTime('2026-10-06T17:15:00Z'),
                usageDate: _krskReset('2026-10-06T17:15:00Z'),
                lane: T('Claude workers'),
            })""")
        finally:
            context.close()

    assert values["en"]["money"] == "$212.8"
    assert values["en"]["number"] == "1,234.5"
    assert "Oct" in values["en"]["analyticsDate"]
    assert "Oct" in values["en"]["usageDate"]
    assert values["en"]["lane"] == "Claude workers"
    assert values["ru"]["money"] == "$212,8"
    assert "окт" in values["ru"]["analyticsDate"].lower()
    assert "окт" in values["ru"]["usageDate"].lower()
    assert values["ru"]["lane"] == "Claude-воркеры"
