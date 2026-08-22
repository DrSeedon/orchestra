"""#369: screenshots of harness tool bubbles for the user (live :8888 + route substitution)."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")
BASE = "http://127.0.0.1:8888"
OUT = Path(__file__).parent


def source(rel: str) -> str:
    return (ROOT / rel).read_text()


CALLS_FULL = [
    ["text", "Готово — прогнал тесты и обновил документацию."],
    ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py\\nls -la app/static/js"}'],
    ["tool_result", "exit_code=0\\n56 passed in 61.51s\\napp.js\\ntool-renderers.js\\nusage.js"],
    ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/static/js/tool-renderers.js","limit":40}'],
    ["tool", 'edit: {"path":"app/ui.py","old":"const a = 1;","new":"const a = 2; // fixed"}'],
    ["tool", 'todo_write: {"todos":[{"content":"проверить рендер бабблов","status":"completed"},{"content":"скриншот для юзера","status":"in_progress"},{"content":"отправить отчёт","status":"pending"}]}'],
    ["tool", 'review: {"focus":"check the diff for regressions before merge"}'],
]

CALLS_COMPACT = [
    ["tool", 'bash: {"command":"uv run pytest -q tests/test_frontend.py"}'],
    ["tool", 'read: {"path":"/home/kesha/orchestra/worktrees/wt/app/ui.py","offset":3,"limit":10}'],
    ["tool", 'todo_write: {"todos":[{"content":"рендер бабблов","status":"completed"},{"content":"скриншот","status":"in_progress"}]}'],
    ["tool", 'review: {"focus":"regressions before merge"}'],
]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 1000})
        for rel, ctype in [
            ("app/static/js/tool-renderers.js", "application/javascript"),
            ("app/static/js/app.js", "application/javascript"),
            ("app/static/css/style.css", "text/css"),
        ]:
            pattern = f"**/static/{rel.split('app/static/')[1]}*"
            body, ct = source(rel), ctype

            def serve(route, _request, b=body, c=ct):
                route.fulfill(status=200, content_type=c, body=b)

            page.route(pattern, serve)
        page.goto(BASE, wait_until="domcontentloaded")
        if page.locator('input[name="password"]').count():
            page.fill('input[name="username"]', os.environ["DASHBOARD_USER"])
            page.fill('input[name="password"]', os.environ["DASHBOARD_PASSWORD"])
            page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.wait_for_function("() => typeof HARNESS_TOOL_ALIASES !== 'undefined'",
                               timeout=10000)
        page.evaluate("""(calls) => {
            selectedAgent = null;
            if (eventSource) { eventSource.close(); eventSource = null; }
            window.compactMode = false;
            const chat = document.querySelector('#chat');
            chat.innerHTML = '';
            for (const [type, content] of calls) {
                addChatEntry(type, content, null, null, {});
            }
        }""", CALLS_FULL)
        page.evaluate("() => { const c = document.querySelector('#chat'); c.scrollTop = c.scrollHeight; }")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "bubbles-full.png"), full_page=False)

        page.evaluate("""(calls) => {
            window.compactMode = true;
            const chat = document.querySelector('#chat');
            chat.innerHTML = '';
            for (const [type, content] of calls) {
                addChatEntry(type, content, null, null, {});
            }
        }""", CALLS_COMPACT)
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "bubbles-compact.png"), full_page=False)
        browser.close()
    print("saved:", OUT / "bubbles-full.png", OUT / "bubbles-compact.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
