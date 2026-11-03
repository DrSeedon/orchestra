"""Observe the existing full dashboard/card test using synthetic optional history."""
import json
import os
from pathlib import Path

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    target = 'tests/test_workflow_cards.py::test_dynamic_workflow_call_renders_detail_card_and_expands_answer'
    if item.nodeid != target:
        yield
        return
    from tests import test_frontend
    original = test_frontend._repo_scope
    original_goto = test_frontend._goto_dashboard
    late_events = []
    def observed_goto(page, *args, **kwargs):
        result = original_goto(page, *args, **kwargs)
        page.wait_for_function("() => typeof _refreshWorkflowCard === 'function'")
        page.expose_function("__recordWorkflowLateGet", lambda event: late_events.append(event))
        page.route("**/api/v1240-background-fixture", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"background":true}'))
        page.evaluate("""() => {
            const refresh = _refreshWorkflowCard;
            _refreshWorkflowCard = async (card, runId) => {
                const again = await refresh(card, runId);
                if (runId === 'V-776-fixture') {
                    await api('/api/v1240-background-fixture');
                    await window.__recordWorkflowLateGet({
                        rendered: card.textContent.includes('First task prompt'),
                        lastUrl: window.__workflowApiPath || null,
                        requested: window.__workflowApiRequests || [],
                        hidden: document.hidden,
                    });
                }
                return again;
            };
        }""")
        return result
    if os.environ.get("V1240_FORCE_LATE_WORKFLOW_GET") == "1":
        test_frontend._goto_dashboard = observed_goto
    # This helper only selects optional historical content; it never changes the
    # workflow API/card assertions. The source-only copy has no Git metadata.
    test_frontend._repo_scope = lambda: str(item.funcargs['tmp_path'] / 'synthetic-optional-history')
    browser = item.funcargs['dashboard_browser']
    pages = []
    def opened(page):
        pages.append(page)
        page.add_init_script('''
            window.__workflowProbeFetches = [];
            const originalFetch = window.fetch.bind(window);
            window.fetch = (...args) => {
                window.__workflowProbeFetches.push(String(args[0]));
                return originalFetch(...args);
            };
        ''')
    browser.on('page', opened)
    try:
        yield
    finally:
        test_frontend._repo_scope = original
        test_frontend._goto_dashboard = original_goto
        browser.remove_listener('page', opened)
        evidence=[]
        for page in pages:
            if page.is_closed():
                evidence.append({'closed':True})
                continue
            evidence.append(page.evaluate('''() => ({
                hidden: document.hidden,
                lastWorkflowApiPath: window.__workflowApiPath || null,
                fetches: (window.__workflowProbeFetches || []).filter(path => path.startsWith('/api/')),
                activeGets: typeof _apiActiveGets !== 'undefined' ? _apiActiveGets : null,
                queueLength: typeof _apiGetQueue !== 'undefined' ? _apiGetQueue.length : null,
                pollInFlight: typeof _pollInFlight !== 'undefined' ? [..._pollInFlight.keys()] : [],
                watchers: [...document.querySelectorAll('[data-is-workflow-card]')].map(card => card.dataset.workflowRunId || null),
            })'''))
        suffix = os.environ.get('V1240_PROBE_LABEL', 'existing')
        (Path(__file__).parent/f'raw/workflow-{suffix}-probe.json').write_text(
            json.dumps({'pages':evidence,'late_get_events':late_events},indent=2)+'\n')
