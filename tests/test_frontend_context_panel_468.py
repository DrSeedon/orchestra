"""#468 — the selected agent's context panel follows completed turns."""

import json

import pytest
from playwright.sync_api import Browser

from tests import test_frontend
from tests.test_frontend import _goto_dashboard, _route_frontend_sources


@pytest.fixture(scope="module")
def dashboard_browser(tmp_path_factory):
    yield from test_frontend.dashboard_browser.__wrapped__(tmp_path_factory)


def test_live_stream_completion_refreshes_selected_agent_context(
    dashboard_browser: Browser,
):
    page = dashboard_browser.new_page()
    _route_frontend_sources(page)
    context_calls = []
    context_payload = {"percentage": 91, "total_tokens": 908000, "max_tokens": 1000000}

    def context_route(route):
        context_calls.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(context_payload),
        )

    page.route("**/api/sessions/fe-orch/context*", context_route)
    _goto_dashboard(page)
    page.wait_for_function("() => typeof _refreshContextAfterTurn === 'function'")
    page.wait_for_function(
        "() => document.querySelector('#ai-context')?.textContent.includes('91%')"
    )
    initial_context_calls = len(context_calls)
    assert initial_context_calls >= 1
    context_payload.update(percentage=95, total_tokens=950000)
    page.evaluate("""() => {
        contextCache['/tmp/fe-scope:fe-orch'] = '91% (908k/1000k)';
        setContextDisplay('91% (908k/1000k)');
        selectedAgent = 'fe-orch';
        currentScope = '/tmp/fe-scope';
        _applyLiveAgentStatus('fe-orch', 'running');
        _applyLiveAgentStatus('fe-orch', 'idle');
    }""")
    page.wait_for_function(
        "() => document.querySelector('#ai-context')?.textContent.includes('95%')"
    )
    page.close()

    assert len(context_calls) == initial_context_calls + 1
