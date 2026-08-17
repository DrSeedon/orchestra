from tests.test_usage_analytics_frontend import _page, _payload


def _open(page):
    page.evaluate("openAnalyticsModal()")
    page.wait_for_timeout(20)


def test_t314_browser_empty_shadow_state_is_explicit(browser):
    page = _page(browser)
    payload = _payload()
    payload["quota_controller"] = {
        "enforcement_active": True,
        "shadow": {"data_available": False, "reason": "no_shadow_telemetry"},
    }
    page.evaluate("payload => { window.api = async () => payload; }", payload)
    _open(page)
    assert "analytics-quota-empty" in page.locator("[data-quota-controller]").get_attribute("class")
    assert "Сегодняшнюю волну Codex нельзя классифицировать" in page.locator("#analytics-body").inner_text()


def test_t314_browser_quota_error_state_is_distinct(browser):
    page = _page(browser)
    payload = _payload()
    payload["quota_controller"] = {
        "data_available": False,
        "reason": "quota_controller_error",
        "error": "OperationalError",
    }
    page.evaluate("payload => { window.api = async () => payload; }", payload)
    _open(page)
    assert "analytics-quota-error" in page.locator("[data-quota-controller]").get_attribute("class")
    assert "Статический гейт сохранён" in page.locator("#analytics-body").inner_text()


def test_t314_browser_quota_cards_and_history_render_without_ids(browser):
    page = _page(browser)
    payload = _payload()
    payload["quota_controller"] = {
        "enforcement_active": True,
        "shadow": {
            "data_available": True,
            "decision_counts": {"would_allow": 2, "would_hold": 1, "indeterminate": 3},
            "actual_hold_count": 1,
            "buckets": [{
                "bucket": "codex:primary",
                "utilization": 88,
                "q95_next_turn_pp": 2.5,
                "reserve_pp": 1,
                "headroom_pp": 7.5,
            }],
            "history": [{
                "created_at": "2026-07-25T07:52:00+00:00",
                "model": "gpt-5.6-codex",
                "would_allow": False,
                "zone": "THROTTLE",
                "reasons": ["q95_guard"],
            }],
        },
    }
    page.evaluate("payload => { window.api = async () => payload; }", payload)
    _open(page)
    body = page.locator("#analytics-body")
    assert "Квоты и история решений" in body.inner_text()
    assert "codex:primary" in body.inner_text()
    assert "q95_guard" in body.inner_text()
    assert page.locator("[data-quota-controller]").locator("[data-decision-id]").count() == 0
