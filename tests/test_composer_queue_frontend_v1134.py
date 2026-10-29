"""Execute production chat.js against synthetic API responses, offline.

The Node tests use a minimal DOM double and stay in the regular test gate.
The browser tests run the identical scenarios with Chromium's actual DOM.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = [
    "states_order_content", "out_of_order", "selection_scope_aba", "stale_404",
    "cancel_success_stale_get", "cancel_loses_claim", "cancel_error_and_poll",
    "cancel_after_switch", "refresh_failure_recovery", "queued_send_is_not_delivered",
    "send_response_after_switch", "upload_switch_and_double_click", "old_backend",
    "cancel_success_poll_refresh_failure", "after_turn_followup_draft", "after_turn_failure_draft",
    "overlapping_slow_polls",
    "accepted_saved_draft_aba", "failed_saved_draft",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_javascript(scenario):
    node = shutil.which("node")
    assert node, "Node is required for the offline production-JavaScript queue regressions"
    result = subprocess.run(
        [node, str(ROOT / "tests/queued_messages_v1134_node.cjs"), scenario],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"PASS {scenario}"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_browser_dom(browser, scenario):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.set_content('''<div id="queued-messages" aria-live="polite"></div>
            <div id="chat"></div><textarea id="chat-input"></textarea>
            <button id="send-btn"></button><button id="send-after-turn-btn"></button>''')
        for script in ("tests/queued_messages_v1134_setup.js", "app/static/js/chat.js",
                       "tests/queued_messages_v1134_scenarios.js"):
            page.add_script_tag(path=str(ROOT / script))
        assert page.evaluate("scenario => runQueueScenario(scenario)", scenario) == scenario
    finally:
        page.close()
