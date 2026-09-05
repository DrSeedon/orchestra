"""Recovery errors cannot strand the dashboard or prevent other refreshes."""

from pathlib import Path
import json

import pytest
from playwright.sync_api import sync_playwright
from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlsplit


@pytest.fixture(scope="module")
def recovery_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("failure", ["sync", "async", "chat_reset"])
def test_recovery_isolates_failure_and_can_run_again(recovery_browser, failure):
    page = recovery_browser.new_page()
    try:
        page.set_content("<body><div id='connection-banner'></div></body>")
        page.evaluate("""() => {
            window.escHtml = text => String(text);
            window.selectedAgent = 'worker'; window.currentScope = '/scope';
            window.resetChatTransientState = () => {};
            window._showChatFor = async () => {};
            window.refreshSessions = async () => {};
            window.loadOrchestrators = async () => {};
            window.loadModels = async () => {};
            window.refreshOpenFolders = async () => {};
            window.fetchUsage = async () => {};
        }""")
        page.add_script_tag(path=str(
            Path(__file__).parents[1] / "app/static/js/connection.js"
        ))
        result = page.evaluate("""async failure => {
            const calls = [];
            refreshSessions = async () => { calls.push('sessions'); };
            refreshOpenFolders = async () => { calls.push('files'); };
            const broken = () => { throw new Error('refresh exploded'); };
            if (failure === 'sync') fetchUsage = broken;
            if (failure === 'async') fetchUsage = async () => broken();
            if (failure === 'chat_reset') resetChatTransientState = broken;
            let escaped = '';
            try { await Connection.recover(); } catch (error) { escaped = error.message; }
            const first = {phase: Connection.state.phase, calls: [...calls],
                banner: document.getElementById('connection-banner').textContent};
            fetchUsage = async () => {};
            resetChatTransientState = () => {};
            await Connection.recover();
            return {escaped, first, calls, phase: Connection.state.phase};
        }""", failure)
        assert result["escaped"] == ""
        assert result["first"]["phase"] == "degraded"
        assert result["first"]["calls"] == ["sessions", "files"]
        assert "refresh exploded" in result["first"]["banner"]
        assert result["calls"] == ["sessions", "files", "sessions", "files"]
        assert result["phase"] == "online"
    finally:
        page.close()


@pytest.mark.parametrize("scenario", [
    "test_new_worker_initial_snapshot_requests_and_renders_last_100_rows",
    "test_authoritative_snapshot_has_no_post_paint_history_staircase",
    "test_chat_open_waits_for_authoritative_snapshot_and_paints_once",
    "test_rapid_chat_switch_aborts_old_snapshot_before_render",
    "test_photo_batch_renders_as_compact_expandable_gallery",
    "test_pasted_image_previews_use_one_bounded_square_size",
    "test_load_more_increases_visible_cards",
    "test_short_snapshot_offers_one_shot_previous_500_without_cache",
    "runtime_status",
])
def test_chat_contracts_without_live_server(recovery_browser, monkeypatch, scenario):
    """Reuse the existing user-scenario oracles without starting app lifespan/CLIs."""
    from tests import test_frontend as frontend

    root = Path(__file__).parents[1] / "app"
    html = Environment(loader=FileSystemLoader(root / "templates")).get_template(
        "dashboard.html"
    ).render(currency_symbol="₽", is_auth_enabled=False, is_owner_mode=False)
    monkeypatch.setattr(frontend, "_DASHBOARD_ORIGIN", "http://stability.invalid")
    session = {"id": "fe-orch-id", "name": "fe-orch", "scope": "/tmp/fe-scope",
               "status": "idle", "model": "gpt-5.6-sol", "runtime": "codex",
               "is_orchestrator": True, "role": "orchestrator", "cost_usd": 0}

    class IsolatedPages:
        def new_page(self):
            page = recovery_browser.new_page()

            def route(request):
                path = urlsplit(request.request.url).path
                if path == "/":
                    request.fulfill(status=200, content_type="text/html", body=html)
                elif path.startswith("/static/"):
                    asset = root / "static" / path.removeprefix("/static/")
                    request.fulfill(path=str(asset))
                else:
                    if path in {"/api/sessions", "/api/orchestrators"}:
                        body = json.dumps([session])
                    elif path == "/api/sessions/fe-orch":
                        body = json.dumps(session)
                    else:
                        body = "[]" if path.endswith("/logs") else "{}"
                    request.fulfill(status=200, content_type="application/json", body=body)

            page.route("**/*", route)
            return page

    if scenario == "runtime_status":
        page = frontend._open_chat_snapshot_page(IsolatedPages())
        try:
            result = page.evaluate("""() => {
                const session = {name:'fe-orch', scope:'/tmp/fe-scope', status:'running',
                    model:'gpt-5.6-sol', runtime_connection:'detached', delivery_uncertain:true};
                currentSessions = [session];
                updateAgentInfo(session);
                const item = createAgentItem(session);
                const before = document.querySelector('#ai-status').textContent;
                _applyLiveAgentStatus('fe-orch', 'idle');
                return {before, title:item.querySelector('.agent-status').title,
                    after:document.querySelector('#ai-status').textContent};
            }""")
            assert result["before"].startswith("● running")
            assert result["after"].startswith("● idle")
            for value in result.values():
                assert "runtime отключён" in value
                assert "доставка не подтверждена" in value
        finally:
            page.close()
    else:
        getattr(frontend, scenario)(IsolatedPages())
