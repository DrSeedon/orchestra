"""Reproduce the #260 regression on the LIVE dashboard (P0 already merged to main).

Prints, for the orchestrator's real Claude stream: how many tool cards carry
data-tool-use-id, and how many results ended up as orphans.
"""

import json
import sys
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

ENV = dotenv_values("/home/kesha/orchestra/.env")
BASE = "http://127.0.0.1:8888"
AGENT = next((a.split("=",1)[1] for a in sys.argv if a.startswith("--agent=")), "Orchestra-orchestrator")
SCOPE = "/home/kesha/orchestra"


def main() -> None:
    substitute = "--substitute" in sys.argv
    local = Path(__file__).parents[3] / "app/static/js/app.js"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"},
        )
        hits = {"n": 0}
        if substitute:
            body = local.read_text()

            def handler(route):
                hits["n"] += 1
                route.fulfill(status=200, content_type="application/javascript", body=body)

            page.route("**/static/js/app.js*", handler)

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            "() => {"
            f"localStorage.setItem('lastOrchScope', {SCOPE!r});"
            f"localStorage.setItem('lastOrchName', {AGENT!r});"
            "localStorage.setItem('compactToolMode', 'false'); }"
        )
        page.goto(BASE, wait_until="load")
        page.wait_for_function(f"() => selectedAgent === {AGENT!r}")
        page.wait_for_function("() => document.querySelectorAll('#chat [data-tool-raw-name]').length > 3")
        page.wait_for_timeout(2500)

        # Старая история (63.7% строк без tool_use_id) достаётся только доборкой вверх.
        for _ in range(int(next((a.split("=")[1] for a in sys.argv if a.startswith("--more=")), 0))):
            btn = page.locator("#load-more-btn")
            if not btn.count() or not btn.is_visible():
                break
            btn.click()
            page.wait_for_timeout(1800)

        out = page.evaluate(
            """() => {
                const chat = document.querySelector('#chat');
                const calls = [...chat.querySelectorAll('[data-tool-raw-name]')];
                const orphans = [...chat.querySelectorAll('[data-unmatched-tool-result]')];
                return {
                    calls: calls.length,
                    callsWithId: calls.filter(c => c.dataset.toolUseId).length,
                    sampleCallIds: calls.slice(-6).map(c => ({
                        tool: c.dataset.toolRawName,
                        id: c.dataset.toolUseId || null,
                        directChild: c.parentElement === chat,
                    })),
                    orphans: orphans.length,
                    orphansWithoutId: orphans.filter(o => !/toolu_|exec-/.test(o.innerText)).length,
                    orphanDiag: orphans.map(o => {
                        const m = o.innerText.match(/toolu_[A-Za-z0-9]+|[a-z]+-[0-9a-f-]{8,}/);
                        const id = m ? m[0] : null;
                        const card = id ? chat.querySelector(
                            `[data-tool-raw-name][data-tool-use-id="${CSS.escape(id)}"]`) : null;
                        return {
                            id,
                            callCardExists: !!card,
                            callIsDirectChild: card ? card.parentElement === chat : null,
                            callParent: card ? card.parentElement.className.slice(0, 60) : null,
                            orphanIsDirectChild: o.parentElement === chat,
                            // is the call BEFORE the orphan in document order?
                            callPrecedes: card
                                ? !!(o.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_PRECEDING)
                                : null,
                            text: o.innerText.slice(0, 60),
                        };
                    }),
                };
            }"""
        )
        out["substitutionHits"] = hits["n"]
        out["pageErrors"] = errors
        print(json.dumps(out, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
