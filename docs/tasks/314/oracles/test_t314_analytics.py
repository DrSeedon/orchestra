from pathlib import Path


ANALYTICS_JS = Path("app/static/js/analytics.js")


def test_t314_analytics_live_request_uses_timeout_above_observed_2_6_seconds():
    source = ANALYTICS_JS.read_text()
    start = source.index("async function _analyticsLoad")
    end = source.index("function _analyticsRender", start)
    load_body = source[start:end]
    assert "timeoutMs: 15000" in load_body


def test_t314_analytics_quota_empty_state_is_explicit():
    source = ANALYTICS_JS.read_text()
    assert "analytics-quota-empty" in source
    assert "no_shadow_telemetry" in source


def test_t314_analytics_quota_error_state_is_distinct():
    source = ANALYTICS_JS.read_text()
    assert "analytics-quota-error" in source
    assert "analytics-quota-history" in source


def test_t314_analytics_exposes_luna_fast_and_sol_suppression():
    source = ANALYTICS_JS.read_text()
    assert "luna_fast_default" in source
    assert "sol_suppression_reason" in source
