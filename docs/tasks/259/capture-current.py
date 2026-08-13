"""Capture the current desktop dashboard and inspect visible chat/tool surfaces."""

import json
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


OUT = Path(__file__).parent
BASE = "http://127.0.0.1:8888"


def main() -> None:
    env = dotenv_values("/home/kesha/orchestra/.env")
    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        context = browser.new_context(
            extra_http_headers=headers,
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.add_init_script(
            """() => {
                localStorage.setItem('lastOrchScope', '/home/kesha/orchestra');
                localStorage.setItem('lastOrchName', 'Orchestra-orchestrator');
            }"""
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE, wait_until="load")
        page.wait_for_function("() => selectedAgent === 'Orchestra-orchestrator'")
        page.wait_for_function("() => document.querySelectorAll('.agent-item').length > 10")
        page.wait_for_timeout(1200)
        page.screenshot(path=OUT / "current-dashboard-1920.png")
        page.locator("#chat").screenshot(path=OUT / "current-chat-1920.png")
        page.locator("#agent-info").locator("..").screenshot(
            path=OUT / "current-agent-sidebar.png"
        )
        observed = page.evaluate(
            """() => ({
                selectedAgent,
                scope: currentScope,
                agents: document.querySelectorAll('.agent-item').length,
                visibleAgents: [...document.querySelectorAll('.agent-item')]
                    .filter(node => node.offsetWidth && node.offsetHeight).length,
                chatChildren: document.querySelector('#chat').children.length,
                toolCards: document.querySelectorAll('#chat [class*="tool"]').length,
                rawCards: [...document.querySelectorAll('#chat [data-chat-log-id]')]
                    .map(node => ({id:node.dataset.chatLogId, text:node.innerText}))
                    .filter(item => /price_rub|## Orchestrators|\bpar\b/.test(item.text))
                    .map(item => ({...item, text:item.text.slice(0, 1000)})),
                chatText: document.querySelector('#chat').innerText.slice(-12000),
                pageErrors: [],
            })"""
        )
        observed["pageErrors"] = errors
        for log_id, filename in (
            ("99085", "current-mispaired-tools.png"),
            ("99138", "current-raw-task-result.png"),
        ):
            node = page.locator(f'[data-chat-log-id="{log_id}"]')
            if node.count():
                node.screenshot(path=OUT / filename)
        print(json.dumps(observed, ensure_ascii=False, indent=2))
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
