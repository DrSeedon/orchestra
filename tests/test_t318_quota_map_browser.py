"""Живая карта квот в Usage Analytics (#318).

Числа фикстур — состояние на 18.08.2026: Claude 7d 4% / 5h 26%, Codex 99%
(Sol и Luna уже отбиваются с weekly_quota_blocked), Spark 1%, Grok без
телеметрии. Пороги в ожиданиях стоят литералами: тест обязан краснеть, когда
их поменяют.
"""

from tests.test_usage_analytics_frontend import _page, _payload

CLAUDE_MODELS = [
    {"model": "claude-opus-5[1m]", "label": "Opus 5", "bucket": "anthropic", "lane": "claude",
     "state": "available", "allowed": True, "threshold": 90.0, "utilization": 4,
     "reason": "weekly utilization 4% is below 90%"},
]
CODEX_MODELS = [
    {"model": "gpt-5.6-sol", "label": "Sol", "bucket": "codex", "lane": "sol",
     "state": "blocked", "allowed": False, "threshold": 95.0, "utilization": 99,
     "reason": "weekly utilization 99% is at or above 95%"},
    {"model": "gpt-5.6-luna", "label": "Luna", "bucket": "codex", "lane": "luna",
     "state": "blocked", "allowed": False, "threshold": 98.0, "utilization": 99,
     "reason": "weekly utilization 99% is at or above 98%"},
]


def _map(**overrides):
    payload = {
        "generated_at": "2026-08-18T09:00:00+00:00",
        "observation_max_age_seconds": 300.0,
        "mode": {
            "deciding": "static_thresholds",
            "policy_available": True,
            "source": "temporary_static_override",
            "label": "TEMPORARY STATIC OVERRIDE",
            "revision": 7,
            "reason": "operator runway correction",
            "updated_at": "2026-08-17T10:00:00+00:00",
            "adaptive_kill_switch_enabled": True,
            "adaptive_tier": "precalibration",
        },
        "policy": {
            "revision": 7,
            "label": "TEMPORARY STATIC OVERRIDE",
            "source": "temporary_static_override",
            "lanes": {
                "claude": {"threshold": 90.0, "revision": 7},
                "sol": {"threshold": 95.0, "revision": 7},
                "luna": {"threshold": 98.0, "revision": 7},
                "spark": {"threshold": 95.0, "revision": 7},
            },
        },
        "buckets": [
            {
                "bucket": "anthropic", "label": "Claude", "fresh": True, "data_available": True,
                "window": {"id": "seven_day", "label": "7d", "window_minutes": 10080,
                           "utilization": 4, "resets_at": "2026-08-25T00:00:00+00:00",
                           "reset_in_seconds": 572400},
                "reference_windows": [{"id": "five_hour", "label": "5h", "window_minutes": 300,
                                       "utilization": 26, "resets_at": "2026-08-18T14:00:00+00:00",
                                       "reset_in_seconds": 18000}],
                "lanes": [{"lane": "claude", "label": "Claude", "threshold": 90.0,
                           "models": ["claude-opus-5[1m]"]}],
                "models": CLAUDE_MODELS,
            },
            {
                "bucket": "codex", "label": "Codex", "fresh": True, "data_available": True,
                "window": {"id": "primary", "label": "7d", "window_minutes": 10080,
                           "utilization": 99, "resets_at": "2026-08-23T00:00:00+00:00",
                           "reset_in_seconds": 399600},
                "reference_windows": [],
                "lanes": [
                    {"lane": "sol", "label": "Sol", "threshold": 95.0, "models": ["gpt-5.6-sol"]},
                    {"lane": "luna", "label": "Luna Fast", "threshold": 98.0, "models": ["gpt-5.6-luna"]},
                ],
                "models": CODEX_MODELS,
            },
            {
                "bucket": "grok", "label": "Grok", "fresh": False, "data_available": False,
                "window": None, "reference_windows": [], "lanes": [], "models": [],
            },
        ],
        "outside_policy": [
            {"model": "grok-4.6", "label": "Grok 4.6", "bucket": "grok", "lane": None,
             "state": "not_applicable", "allowed": True, "threshold": None,
             "utilization": None, "reason": "Grok is outside the subscription weekly quota policy"},
        ],
    }
    payload.update(overrides)
    return payload


def _open(browser, map_payload=None, policy_payload=None):
    page = _page(browser)
    analytics = _payload()
    analytics["quota_map"] = map_payload if map_payload is not None else _map()
    page.evaluate(
        """data => {
            window.quotaCalls = [];
            window.api = async (url, options) => {
                window.quotaCalls.push({ url, options: options || null });
                if (url.startsWith('/api/usage/quota-controller/policy')) return structuredClone(data.policy);
                return structuredClone(data.analytics);
            };
        }""",
        {
            "policy": policy_payload if policy_payload is not None else {
                "audit": [{"actor": "kesha", "created_at": "2026-08-17T10:00:00+00:00",
                           "action": "update", "reason": "operator runway correction",
                           "revision": 7}],
            },
            "analytics": analytics,
        },
    )
    page.evaluate("openAnalyticsModal()")
    page.wait_for_selector("[data-quota-map]")
    return page


def test_map_costs_no_extra_request_on_open(browser):
    page = _open(browser)
    assert page.evaluate("() => window.quotaCalls.map(c => c.url)") == [
        "/api/usage/analytics?days=7",
    ]
    assert page.locator("[data-quota-pool]").count() == 3


def test_blocked_pool_is_red_and_names_the_models_it_stops(browser):
    page = _open(browser)
    codex = page.locator("[data-quota-pool='codex']")
    assert codex.count() == 1
    assert "quota-pool-blocked" in codex.get_attribute("class")
    status = codex.locator("[data-quota-status]").inner_text()
    assert "заблокировано" in status and "Sol" in status and "Luna" in status
    chips = codex.locator("[data-quota-model]")
    assert chips.count() == 2
    classes = [chips.nth(i).get_attribute("class") for i in range(chips.count())]
    assert classes and all("quota-chip-blocked" in item for item in classes)
    claude = page.locator("[data-quota-pool='anthropic']")
    assert "quota-pool-ok" in claude.get_attribute("class")
    assert "quota-chip-ok" in claude.locator("[data-quota-model='claude-opus-5[1m]']").get_attribute("class")


def test_claude_weekly_decides_and_five_hour_is_reference_only(browser):
    page = _open(browser)
    claude = page.locator("[data-quota-pool='anthropic']")
    assert claude.locator("[data-quota-utilization]").inner_text().startswith("4")
    marks = claude.locator("[data-quota-mark]")
    assert marks.count() == 1
    assert marks.nth(0).get_attribute("data-quota-mark") == "claude"
    assert "90" in marks.nth(0).inner_text()
    text = claude.inner_text()
    assert "5h 26%" in text
    assert "справочно, допуск решает только недельное окно" in text


def test_pool_without_weekly_telemetry_says_no_data_not_zero(browser):
    page = _open(browser)
    grok = page.locator("[data-quota-pool='grok']")
    assert grok.count() == 1
    assert "quota-pool-nodata" in grok.get_attribute("class")
    assert "нет данных" in grok.locator("[data-quota-status]").inner_text()
    assert grok.locator("[data-quota-bar]").count() == 0
    assert "0%" not in grok.inner_text()
    assert "Grok 4.6" in page.locator("[data-quota-outside]").inner_text()


def test_panel_says_which_mode_decides_and_who_the_threshold_stops(browser):
    page = _open(browser)
    mode = page.locator("[data-quota-mode]").inner_text()
    assert "Сейчас режет ход: статический порог" in mode
    assert "TEMPORARY STATIC OVERRIDE" in mode
    assert "revision 7" in mode
    assert "Адаптивный контроллер (#314)" in mode and "killswitch включён" in mode
    note = page.locator("[data-quota-orchestrator-note]").inner_text()
    assert "воркеров" in note and "оркестратор" in note.lower()


def test_threshold_slider_writes_through_the_policy_endpoint(browser):
    page = _open(browser)
    assert "90%" in page.locator("[data-quota-threshold-value='claude']").inner_text()
    page.locator("[data-quota-threshold='claude']").fill("85")
    page.locator("[data-quota-threshold='claude']").dispatch_event("input")
    assert "85%" in page.locator("[data-quota-threshold-value='claude']").inner_text()
    page.locator("[data-quota-policy-reason]").fill("резерв под оркестратора")
    page.locator("[data-quota-policy-save]").click()
    page.wait_for_function(
        "() => window.quotaCalls.some(c => c.options && c.options.method === 'PUT')"
    )
    put = page.evaluate(
        "() => window.quotaCalls.filter(c => c.options && c.options.method === 'PUT')"
    )
    assert len(put) == 1
    assert put[0]["url"] == "/api/usage/quota-controller/policy"
    body = __import__("json").loads(put[0]["options"]["body"])
    assert body["thresholds"]["claude"] == 85
    assert body["thresholds"]["luna"] == 98
    assert body["expected_revision"] == 7
    assert body["reason"] == "резерв под оркестратора"


def test_save_without_reason_sends_nothing(browser):
    page = _open(browser)
    page.locator("[data-quota-policy-save]").click()
    page.wait_for_timeout(100)
    assert page.evaluate(
        "() => window.quotaCalls.filter(c => c.options && c.options.method === 'PUT').length"
    ) == 0


def test_audit_is_loaded_on_demand_and_names_who_changed_the_policy(browser):
    page = _open(browser)
    # До нажатия журнал не читался: пустая строка не должна выдаваться за «правок не было».
    assert "kesha" not in page.locator("[data-quota-policy-audit]").inner_text()
    page.locator("[data-quota-policy-audit-load]").click()
    page.wait_for_selector("[data-quota-policy-audit-load]", state="detached")
    audit = page.locator("[data-quota-policy-audit]").inner_text()
    assert "kesha" in audit and "operator runway correction" in audit
    assert page.evaluate(
        "() => window.quotaCalls.filter(c => c.url.includes('quota-controller/policy')).length"
    ) == 1
