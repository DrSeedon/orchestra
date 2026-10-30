"""Execute production chat.js against synthetic API responses, offline.

The Node tests use a minimal DOM double and stay in the regular test gate.
The browser tests run the identical scenarios with Chromium's actual DOM.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = [
    "queued_send_is_not_delivered", "send_response_after_switch",
    "upload_switch_and_double_click", "after_turn_followup_draft", "after_turn_failure_draft",
    "accepted_saved_draft_aba", "failed_saved_draft",
]


def _draft_functions():
    """Production saveDraft/restoreDraft from app.js (the rest of app.js needs the full page)."""
    source = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
    parts = []
    for name in ("saveDraft", "restoreDraft"):
        match = re.search(rf"^function {name}\(\) \{{\n[\s\S]*?\n\}}\n", source, re.M)
        assert match, f"{name} not found in app.js"
        parts.append(match.group(0))
    return "\n".join(parts)


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
        page.set_content('''<div id="chat"></div><textarea id="chat-input"></textarea>
            <button id="send-btn"></button><button id="send-after-turn-btn"></button>''')
        for script in ("tests/queued_messages_v1134_setup.js", "app/static/js/chat.js"):
            page.add_script_tag(path=str(ROOT / script))
        page.add_script_tag(content=_draft_functions())
        page.add_script_tag(path=str(ROOT / "tests/queued_messages_v1134_scenarios.js"))
        assert page.evaluate("scenario => runQueueScenario(scenario)", scenario) == scenario
    finally:
        page.close()

