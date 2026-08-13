"""Capture the implemented #260 task/agent cards from the worktree frontend."""

from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parents[3]
OUT = Path(__file__).parent / "p1-operational-cards.png"


def main() -> None:
    token = dotenv_values("/home/kesha/orchestra/.env")["INTERNAL_TOKEN"]
    source = (ROOT / "app/static/js/app.js").read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Authorization": f"Bearer {token}"},
        )
        page.route(
            "**/static/js/app.js*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=source,
            ),
        )
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8888", wait_until="load")
        page.wait_for_function("() => typeof _agentResultSummary === 'function'")
        page.evaluate("""() => {
            selectedAgent = null;
            eventSource?.close();
            eventSource = null;
            window.compactMode = false;
            document.querySelector('#chat').innerHTML = '';
            addChatEntry('tool', 'mcp__orchestra__task_create: {"title":"Fix parallel tool results"}', null, null, {id:1, tool_use_id:'capture-task'});
            addChatEntry('tool_result', JSON.stringify({
                par:'ORC-260', id:9001, task_id:9001,
                title:'Fix parallel tool results', project:'Orchestra',
                price_rub:0, status:'new', priority:0,
                description:'Each result stays with its own call. Raw fields remain available when debugging.',
            }), null, null, {id:2, tool_use_id:'capture-task'});
            addChatEntry('tool', 'mcp__orchestra__list_agents: {}', null, null, {id:3, tool_use_id:'capture-agents'});
            addChatEntry('tool_result', [
                '## Orchestrators',
                '🟢 👑 **Orchestra-orchestrator** | running | opus | ctx:31% | "Coordinates work"',
                '🟡 ⚙️ **frontend** | waiting | sol | ctx:42% | 260 | "Waiting for review"',
                '❌ ⚙️ **broken-worker** | broken | sol | ctx:18% | 259 | "Needs restart"',
            ].join('\\n'), null, null, {id:4, tool_use_id:'capture-agents'});
            document.querySelector('#chat').scrollTop = 0;
        }""")
        page.locator("#chat").evaluate("node => node.scrollTop = 0")
        page.locator("#chat").screenshot(path=OUT)
        assert not errors, errors
        print(OUT)
        page.close()
        browser.close()


if __name__ == "__main__":
    main()
