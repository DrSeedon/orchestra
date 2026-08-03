from pathlib import Path
import re

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright


ROOT = Path(__file__).parent.parent
ANALYTICS_JS = ROOT / "app/static/js/analytics.js"
APP_JS = ROOT / "app/static/js/app.js"
USAGE_JS = ROOT / "app/static/js/usage.js"
UTILS_JS = ROOT / "app/static/js/utils.js"
TEMPLATE = ROOT / "app/templates/dashboard.html"


def test_frontend_provider_metadata_is_exhaustive():
    from app.models import PROVIDER_METADATA

    source = UTILS_JS.read_text()
    colors_block = source.split("const _PROVIDER_COLORS = {", 1)[1].split("};", 1)[0]
    color_ids = {
        quoted or bare
        for quoted, bare in re.findall(
            r"(?:'([^']+)'|([a-z][a-z0-9_-]*))\s*:",
            colors_block,
        )
    }
    block = source.split("const _PROVIDER_META = {", 1)[1].split(
        "\n};\nconst _PROVIDER_CAPACITY_KEY",
        1,
    )[0]
    frontend_ids = set(re.findall(r"^    ([a-z][a-z0-9_]*): \{$", block, re.MULTILINE))

    assert frontend_ids == set(PROVIDER_METADATA)
    assert "unknown" in frontend_ids
    assert "opencode" in frontend_ids
    model_providers = {
        provider
        for metadata in PROVIDER_METADATA.values()
        for provider in metadata.model_providers
    }
    assert model_providers <= color_ids


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _payload():
    return {
        "generated_at": "2026-07-25T07:52:00+00:00",
        "period": {
            "days": 7,
            "complete": True,
            "observed_from": "2026-07-18T00:00:00+00:00",
            "observed_to": "2026-07-25T07:52:00+00:00",
        },
        "capacity": {
            "anthropic": {
                "five_hour": {
                    "utilization": 68,
                    "resets_at": "2026-07-25T08:00:00Z",
                },
                "seven_day": {
                    "utilization": 45,
                    "resets_at": "2026-07-28T07:00:00Z",
                },
            },
            "codex": {
                "primary": {
                    "utilization": 33,
                    "window_minutes": 10080,
                    "resets_at": "2026-07-30T10:25:45Z",
                },
                "spark": {
                    "primary": {
                        "utilization": 1,
                        "window_minutes": 10080,
                        "resets_at": "2026-07-31T13:54:00Z",
                    },
                },
            },
            "grok": {
                "primary": {
                    "utilization": 10,
                    "window_minutes": 10080,
                    "resets_at": "2026-08-01T18:49:05Z",
                },
            },
        },
        "wake_after_reset": {
            "candidate_count": 2,
            "monthly_agents": [],
            "manual_action_url": None,
            "scheduled": [],
        },
        "summary": {
            "observed_cost_usd": 1156.25,
            "agent_turns": 716,
            "completed_tasks": 17,
            "linked_completed_tasks": 12,
            "fully_observed_linked_tasks": 12,
            "task_cost_coverage_complete": True,
            "cost_per_linked_task": 21.62,
            "lifetime": {
                "agents": 297,
                "active_agents": 1,
                "cost_usd": 10689.92,
                "turns": 23217,
                "tool_calls": 25775,
            },
        },
        "providers": {
            "claude": {
                "turns": 534,
                "cost_usd": 703.56,
                "comparable_turns": 507,
                "cold_starts": 68,
                "cache_hit_pct": 86.6,
                "cache_ttl_seconds": 3600,
                "cache_ttl_approximate": False,
            },
            "codex": {
                "turns": 182,
                "cost_usd": 452.69,
                "comparable_turns": 133,
                "cold_starts": 38,
                "cache_hit_pct": 71.4,
                "cache_ttl_seconds": 1800,
                "cache_ttl_approximate": True,
            },
            "grok": {
                "turns": 12,
                "cost_usd": 4.5,
                "comparable_turns": 8,
                "cold_starts": 2,
                "cache_hit_pct": 75,
                "cache_ttl_seconds": 1800,
                "cache_ttl_approximate": False,
            },
        },
        "daily": [
            {
                "day": "2026-07-24",
                "turns": 111,
                "cost_usd": 143.02,
                "providers": {
                    "claude": {"cost_usd": 39.17, "turns": 76},
                    "codex": {"cost_usd": 103.85, "turns": 35},
                },
            },
            {
                "day": "2026-07-25",
                "turns": 40,
                "cost_usd": 33.33,
                "providers": {
                    "claude": {"cost_usd": 8.34, "turns": 17},
                    "codex": {"cost_usd": 24.99, "turns": 23},
                },
            },
        ],
        "agents": [
            {
                "id": "a",
                "name": "Orchestra-orchestrator",
                "scope": "/scope",
                "model": "claude-opus-5[1m]",
                "provider": "claude",
                "turns": 151,
                "cost_usd": 263.36,
                "cost_per_turn": 1.74,
                "last_turn": "2026-07-25T07:52:00Z",
                "anomaly": False,
            },
            {
                "id": "b",
                "name": "research-codex-cache",
                "scope": "/scope",
                "model": "gpt-5.6-sol",
                "provider": "codex",
                "turns": 2,
                "cost_usd": 22.21,
                "cost_per_turn": 11.11,
                "last_turn": "2026-07-18T09:43:00Z",
                "anomaly": True,
            },
        ],
        "models": [
            {
                "model": "claude-opus-5[1m]",
                "provider": "claude",
                "turns": 534,
                "cost_usd": 703.56,
                "cost_share_pct": 60.8,
            },
            {
                "model": "gpt-5.6-sol",
                "provider": "codex",
                "turns": 182,
                "cost_usd": 452.69,
                "cost_share_pct": 39.2,
            },
        ],
        "reliability": {
            "subagents": {
                "completed": 221,
                "failed": 19,
                "running": 5,
                "stopped": 1,
            },
            "voice": {"entries": 12, "duration_sec": 193.2, "cost_usd": 0.0167},
            "task_linkage": {"linked": 12, "total": 17},
            "tool_errors": {
                "collector_ready": False,
                "recorded_rows": 0,
                "items": [],
            },
            "turn_usage": {
                "collector_ready": False,
                "recorded_rows": 0,
                "observed_from": None,
            },
        },
    }


def _page(browser: Browser, width=1600, height=1000) -> Page:
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_content(
        """
        <body data-currency="₽">
          <div id="analytics-modal" class="hidden">
            <div class="analytics-shell">
              <div id="analytics-periods"></div>
              <button id="analytics-close">×</button>
              <div id="analytics-view-tabs"></div>
              <div id="analytics-quality"></div>
              <div id="analytics-body"></div>
            </div>
          </div>
        </body>
        """
    )
    page.evaluate(
        """payload => {
            window.marked = {
                setOptions() {},
                parse(value) { return value; },
            };
            window.DOMPurify = { addHook() {} };
            window.MODEL_COST_CURRENCY = '$';
            window.analyticsCalls = [];
            window.api = async url => {
                window.analyticsCalls.push(url);
                return structuredClone(payload);
            };
            window.Chart = class {
                constructor() { this.destroyed = false; }
                destroy() { this.destroyed = true; }
            };
        }""",
        _payload(),
    )
    page.add_style_tag(path=str(ROOT / "app/static/css/style.css"))
    page.add_script_tag(path=str(UTILS_JS))
    page.add_script_tag(path=str(ANALYTICS_JS))
    return page


def test_template_uses_wide_analytics_shell_and_leaf_script():
    source = TEMPLATE.read_text()

    assert "analytics-shell" in source
    assert "max-w-3xl" not in source.split('id="analytics-modal"', 1)[1].split(
        "<!-- Agent activity modal -->", 1
    )[0]
    # #9 заменил прямые пути на версионные: `{{ static_url('js/analytics.js') }}`
    assert "static_url('js/analytics.js')" in source


def test_model_cost_and_task_money_have_separate_currency_sources(browser):
    utils = UTILS_JS.read_text()
    analytics = ANALYTICS_JS.read_text()
    app = APP_JS.read_text()
    usage = USAGE_JS.read_text()
    model_modal = app.split("async function _renderClientModal()", 1)[1].split(
        "async function _refreshModels", 1
    )[0]
    task_renderer = "const _TASK_PRIORITY_META" + app.split(
        "const _TASK_PRIORITY_META", 1
    )[1].split("// Central renderer", 1)[0]

    assert "const CUR = document.body.dataset.currency || '₽';" in utils
    assert "const MODEL_COST_CURRENCY = '$';" in utils
    assert "dataset.currency" not in analytics
    assert "dataset.currency" not in app
    assert "dataset.currency" not in usage
    assert "MODEL_COST_CURRENCY" in model_modal
    assert not re.search(r"\bCUR\b", model_modal)
    assert "MODEL_COST_CURRENCY" not in task_renderer

    page = browser.new_page()
    page.set_content('<body data-currency="€"><div id="task-money"></div></body>')
    page.add_script_tag(content=utils)
    page.add_script_tag(content=task_renderer)
    page.evaluate(
        """() => {
            document.querySelector('#task-money').innerHTML = _taskCardBodyHtml({
                price_rub: 1200,
                paid_rub: 500,
                debt_rub: 700,
            });
        }"""
    )
    task_money = page.locator("#task-money").inner_text()
    assert "Price: 1 200 €" in task_money
    assert "Paid: 500 €" in task_money
    assert "Debt: 700 €" in task_money
    assert "$" not in task_money
    page.close()

    template = TEMPLATE.read_text()
    assert template.index("js/utils.js") < template.index(
        "js/usage.js"
    ) < template.index("js/analytics.js") < template.index(
        "js/app.js"
    )


def test_analytics_renders_usd_when_task_currency_is_rubles(browser):
    page = _page(browser)
    page.evaluate("openAnalyticsModal()")

    costs = page.locator(
        ".analytics-provider-head > strong, .analytics-kpi-grid > article:first-child strong"
    ).all_text_contents()
    assert costs
    assert all(value.startswith("$") for value in costs)
    assert all("₽" not in value for value in costs)
    page.close()


def test_modal_uses_one_snapshot_request_and_tabs_do_not_refetch(browser):
    page = _page(browser)

    page.evaluate("openAnalyticsModal()")
    expect(page.locator("[data-analytics-provider]")).to_have_count(3)
    expect(page.locator('[data-analytics-provider="grok"]')).to_contain_text("10%")
    assert page.evaluate("analyticsCalls") == ["/api/usage/analytics?days=7"]

    page.locator('[data-analytics-period="month"]').click()
    expect(page.locator("#analytics-body")).to_contain_text("Пулы и расходы")
    assert page.evaluate("analyticsCalls") == [
        "/api/usage/analytics?days=7",
        "/api/usage/analytics?days=30",
    ]

    page.locator('[data-analytics-view="agents"]').click()
    expect(page.locator("#analytics-agent-table tr")).to_have_count(2)
    assert len(page.evaluate("analyticsCalls")) == 2
    page.close()


def test_wake_button_schedules_once_and_renders_post_decision(browser):
    page = _page(browser)
    page.evaluate(
        """() => {
            const analyticsPayload = structuredClone(window.analyticsFixture || {});
            const originalApi = window.api;
            window.api = async (url, options = {}) => {
                if (url === '/api/usage/wake-after-reset') {
                    window.analyticsCalls.push(url);
                    return {
                        candidate_count: 2,
                        scheduled: [{
                            provider: 'anthropic',
                            reason: 'base_reset',
                            reset_at: '2026-07-25T08:00:00Z',
                            agents: ['monthly-worker', 'timed-worker'],
                        }],
                        manual: [],
                        unavailable: [],
                        warnings: [],
                    };
                }
                return originalApi(url, options);
            };
        }"""
    )
    page.evaluate("openAnalyticsModal()")

    page.locator("[data-analytics-wake]").click()

    expect(page.locator("[data-analytics-wake-status]")).to_contain_text("anthropic")
    expect(page.locator("[data-analytics-wake-status]")).to_contain_text(
        "monthly-worker"
    )
    expect(page.locator("[data-analytics-wake-status]")).to_contain_text(
        "timed-worker"
    )
    assert page.evaluate("analyticsCalls").count("/api/usage/wake-after-reset") == 1
    page.close()


def test_monthly_limit_panel_requires_manual_action(browser):
    payload = _payload()
    payload["wake_after_reset"] = {
        "candidate_count": 1,
        "scheduled": [],
        "manual": [{
            "provider": "anthropic",
            "reason": "base capacity has no timed reset",
            "agents": ["monthly-worker"],
            "manual_action_url": "https://claude.ai/settings/usage",
        }],
        "unavailable": [],
        "warnings": [],
    }
    page = _page(browser)
    page.evaluate(
        """payload => {
            window.api = async url => {
                window.analyticsCalls.push(url);
                return structuredClone(payload);
            };
        }""",
        payload,
    )

    page.evaluate("openAnalyticsModal()")

    expect(page.locator("[data-analytics-wake-status]")).to_contain_text(
        "не сбрасывается по таймеру"
    )
    expect(page.locator("[data-analytics-wake-status] a")).to_have_attribute(
        "href", "https://claude.ai/settings/usage"
    )
    page.close()


def test_wake_panel_renders_all_decision_groups_together(browser):
    payload = _payload()
    payload["wake_after_reset"] = {
        "candidate_count": 4,
        "scheduled": [{
            "provider": "anthropic",
            "reason": "available_now",
            "reset_at": None,
            "agents": ["wake-now"],
        }],
        "manual": [{
            "provider": "anthropic",
            "reason": "base capacity has no timed reset",
            "agents": ["manual-worker"],
            "manual_action_url": "https://claude.ai/settings/usage",
        }],
        "unavailable": [{
            "provider": "codex",
            "reason": "fresh usage unavailable",
            "agents": ["unknown-worker"],
        }],
        "warnings": [{
            "provider": "grok",
            "reason": "refresh failed; existing timer does not cover current turn",
            "agents": ["changed-turn-worker"],
        }],
    }
    page = _page(browser)
    page.evaluate(
        """payload => {
            window.api = async url => {
                window.analyticsCalls.push(url);
                return structuredClone(payload);
            };
        }""",
        payload,
    )

    page.evaluate("openAnalyticsModal()")

    status = page.locator("[data-analytics-wake-status]")
    for name in (
        "wake-now",
        "manual-worker",
        "unknown-worker",
        "changed-turn-worker",
    ):
        expect(status).to_contain_text(name)
    expect(status.locator("a")).to_have_attribute(
        "href", "https://claude.ai/settings/usage"
    )
    page.close()


def test_wake_click_with_no_action_is_explicitly_acknowledged(browser):
    page = _page(browser)
    page.evaluate(
        """() => {
            const originalApi = window.api;
            window.api = async (url, options = {}) => {
                if (url === '/api/usage/wake-after-reset') {
                    window.analyticsCalls.push(url);
                    return {
                        candidate_count: 1,
                        scheduled: [],
                        manual: [],
                        unavailable: [],
                        warnings: [],
                    };
                }
                return originalApi(url, options);
            };
        }"""
    )
    page.evaluate("openAnalyticsModal()")

    page.locator("[data-analytics-wake]").click()

    expect(page.locator("[data-analytics-wake-status]")).to_contain_text(
        "Ничего не запланировано"
    )
    page.close()


def test_period_change_ignores_stale_snapshot_response(browser):
    page = _page(browser)
    page.evaluate(
        """payload => {
            window.analyticsDeferred = {};
            window.analyticsFixture = payload;
            window.api = url => new Promise(resolve => {
                window.analyticsDeferred[url] = resolve;
            });
        }""",
        _payload(),
    )
    page.evaluate("openAnalyticsModal()")
    page.locator('[data-analytics-period="month"]').click()

    page.evaluate("""() => {
        const payload = structuredClone(window.analyticsFixture);
        payload.period.days = 30;
        window.analyticsDeferred['/api/usage/analytics?days=30'](payload);
    }""")
    page.wait_for_function("() => _analyticsPayload?.period?.days === 30")
    page.evaluate("""() => {
        const payload = structuredClone(window.analyticsFixture);
        payload.period.days = 7;
        window.analyticsDeferred['/api/usage/analytics?days=7'](payload);
    }""")
    page.wait_for_timeout(50)

    assert page.evaluate("_analyticsPayload.period.days") == 30
    page.close()


def test_agent_filters_drilldown_and_reliability_are_honest(browser):
    page = _page(browser)
    page.evaluate("openAnalyticsModal()")

    page.locator('[data-analytics-view="agents"]').click()
    page.locator('[data-analytics-agent-filter="anomaly"]').click()
    expect(page.locator("#analytics-agent-table tr")).to_have_count(1)
    page.locator("#analytics-agent-table tr").click()
    expect(page.locator("#analytics-agent-detail")).to_contain_text(
        "research-codex-cache"
    )

    page.locator('[data-analytics-view="reliability"]').click()
    expect(page.locator("#analytics-body")).to_contain_text("нет collector")
    expect(page.locator("#analytics-body")).not_to_contain_text("0 tool errors")
    assert len(page.evaluate("analyticsCalls")) == 1
    page.close()


def test_partial_tool_error_coverage_does_not_claim_zero(browser):
    page = _page(browser)
    page.evaluate("""() => {
        const original = window.api;
        window.api = async url => {
            const payload = await original(url);
            payload.reliability.tool_errors = {
                collector_ready: true,
                coverage_complete: false,
                collector_started_at: '2026-07-25T07:00:00Z',
                recorded_rows: 0,
                items: [],
            };
            return payload;
        };
    }""")
    page.evaluate("openAnalyticsModal()")
    page.locator('[data-analytics-view="reliability"]').click()

    expect(page.locator("#analytics-body")).to_contain_text("частичное покрытие")
    expect(page.locator("#analytics-body")).not_to_contain_text(
        "Ошибок в собранном окне нет"
    )
    page.close()


def test_partial_task_cost_coverage_does_not_show_exact_price(browser):
    page = _page(browser)
    page.evaluate("""() => {
        const original = window.api;
        window.api = async url => {
            const payload = await original(url);
            payload.summary.linked_completed_tasks = 1;
            payload.summary.fully_observed_linked_tasks = 0;
            payload.summary.task_cost_coverage_complete = false;
            payload.summary.cost_per_linked_task = null;
            return payload;
        };
    }""")
    page.evaluate("openAnalyticsModal()")

    expect(page.locator("#analytics-body")).to_contain_text("частичные данные")
    expect(page.locator("#analytics-body")).to_contain_text("точно измерено 0 / 1")
    page.close()


def test_modal_has_no_document_overflow_at_390px(browser):
    page = _page(browser, width=390, height=844)
    page.evaluate("openAnalyticsModal()")
    expect(page.locator("#analytics-modal")).to_be_visible()

    assert page.locator("body").evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.locator(".analytics-shell").evaluate(
        "el => el.getBoundingClientRect().right <= innerWidth"
    )
    page.close()


def test_leaf_module_does_not_call_legacy_analytics_endpoints():
    source = ANALYTICS_JS.read_text()

    assert "/api/usage/analytics" in source
    assert "/api/usage/daily" not in source
    assert "/api/usage/daily/agents" not in source
    assert "/api/stats" not in source
