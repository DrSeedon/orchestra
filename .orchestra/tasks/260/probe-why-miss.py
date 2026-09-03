"""Instrument _toolForResult on the live dashboard and record WHY a lookup misses."""

import json
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ENV = dotenv_values("/home/kesha/orchestra/.env")
LOCAL = Path(__file__).parents[3] / "app/static/js/app.js"
NEEDLE = "function _toolForResult(chat, payload, anchor, compact) {"
PATCH = """function _toolForResult(chat, payload, anchor, compact) {
    const __id = payload && payload.tool_use_id;
    const __r = __toolForResultOrig(chat, payload, anchor, compact);
    if (__id && !__r) {
        const all = [...chat.querySelectorAll('[data-tool-use-id]')];
        window.__misses = window.__misses || [];
        window.__misses.push({
            id: __id,
            compact: !!compact,
            hasAnchor: !!anchor,
            anchorTag: anchor ? (anchor.dataset.chatNavKind || anchor.tagName) : null,
            cardInDom: all.some(n => n.dataset.toolUseId === __id),
            cardIsDirectChild: all.filter(n => n.dataset.toolUseId === __id)
                .map(n => n.parentElement === chat),
            totalCards: all.length,
        });
    }
    return __r;
}
function __toolForResultOrig(chat, payload, anchor, compact) {"""


def main() -> None:
    body = LOCAL.read_text()
    assert body.count(NEEDLE) == 1, body.count(NEEDLE)
    body = body.replace(NEEDLE, PATCH)
    hits = {"n": 0}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"},
        )

        def handler(route):
            hits["n"] += 1
            route.fulfill(status=200, content_type="application/javascript", body=body)

        page.route("**/static/js/app.js*", handler)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            "() => { localStorage.setItem('lastOrchScope', '/home/kesha/orchestra');"
            "localStorage.setItem('lastOrchName', 'Orchestra-orchestrator');"
            "localStorage.setItem('compactToolMode', 'false'); }"
        )
        page.goto("http://127.0.0.1:8888", wait_until="load")
        page.wait_for_function("() => typeof __toolForResultOrig === 'function'")
        page.wait_for_function("() => selectedAgent === 'Orchestra-orchestrator'")
        page.wait_for_timeout(4000)
        out = {
            "substitutionHits": hits["n"],
            "misses": page.evaluate("() => window.__misses || []"),
            "pageErrors": errors,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
