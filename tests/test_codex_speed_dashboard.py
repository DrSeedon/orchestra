"""Exercise the real Codex control in Chromium against the session API."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from app import db
from app.session import AgentSession


@pytest.mark.parametrize("width", [390, 1280])
def test_codex_speed_control_changes_only_the_selected_chat(width):
    from app.main import app

    db.init_db()
    scope = "/speed-demo"
    models = {"sol": ("gpt-6.2-sol", "codex"), "other": ("gpt-6.2-sol", "codex"),
              "hub": ("hub-gpt-6.2-sol", "hub")}
    for name, (model, runtime) in models.items():
        session = AgentSession(id=name, name=name, scope=scope, cwd=scope,
                               model=model, backend_type=runtime)
        db.save_session(session._to_db_dict())

    root = Path(__file__).resolve().parents[1] / "app/static"
    client = TestClient(app)
    html = re.sub(r"<script\b[^>]*>.*?</script>|<link\b[^>]*>", "", client.get("/").text, flags=re.S)
    requests = []

    def route_dashboard(route):
        request = route.request
        path = request.url.removeprefix("http://orchestra.test")
        if path == "/":
            return route.fulfill(body=html, content_type="text/html")
        if request.method == "POST" and path.endswith("/codex-speed"):
            payload = request.post_data_json
            requests.append((path, payload))
            response = client.post(path, json=payload)
            return route.fulfill(status=response.status_code, body=response.text, content_type="application/json")
        route.abort()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.add_init_script("localStorage.setItem('orch_lang', 'en')")
            page.route("**/*", route_dashboard)
            page.goto("http://orchestra.test/")
            for stylesheet in ("design-system.css", "style.css", "vendor/tailwind.css"):
                page.add_style_tag(path=str(root / "css" / stylesheet))
            for script in ("i18n.js", "utils.js", "connection.js", "chat.js", "app.js"):
                page.add_script_tag(path=str(root / "js" / script))
            page.evaluate("""sessions => {
                currentScope = '/speed-demo';
                selectedAgent = 'sol';
                currentSessions = sessions;
                $('#codex-speed-select').addEventListener('change', changeCodexSpeed);
                renderCodexSpeed();
            }""", client.get("/api/sessions", params={"scope": scope}).json())

            control = page.get_by_label("Codex speed", exact=True)
            expect(control).to_be_visible()
            expect(control).to_have_value("standard")
            control.select_option("fast")
            expect(control).to_be_enabled()
            expect(control).to_have_value("fast")
            expect(page.locator("#codex-speed-hint")).to_contain_text("2×")
            assert requests == [("/api/sessions/sol/codex-speed", {"scope": scope, "speed": "fast"})]

            page.evaluate("selectedAgent = 'other'; renderCodexSpeed();")
            expect(control).to_have_value("standard")
            page.evaluate("selectedAgent = 'hub'; renderCodexSpeed();")
            expect(control).to_be_hidden()
            page.evaluate("""sessions => {
                currentSessions = sessions;
                selectedAgent = 'sol';
                renderCodexSpeed();
            }""", client.get("/api/sessions", params={"scope": scope}).json())
            expect(control).to_have_value("fast")
            control.select_option("standard")
            expect(control).to_be_enabled()
            assert db.get_session("sol")["codex_speed"] == "standard"
        finally:
            browser.close()
