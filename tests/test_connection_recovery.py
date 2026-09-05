"""Recovery errors cannot strand the dashboard or prevent other refreshes."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


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
