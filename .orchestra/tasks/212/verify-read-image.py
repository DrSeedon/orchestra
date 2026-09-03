"""Live browser acceptance for #212 using a real persisted Read image result."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
APP_JS = ROOT / "app/static/js/app.js"
OUT = Path(__file__).with_name("read-image-restored.png")
BASE = "http://127.0.0.1:8888"
TOOL_ID = 70425
RESULT_ID = 70427
IMAGE_PATH = "/home/kesha/orchestra/data/uploads/0d6cf8360135.webp"


def main() -> None:
    env = dotenv_values("/home/kesha/orchestra/.env")
    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
    hits = {"app.js": 0, "missing_source": 0, "full_log": 0}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(extra_http_headers=headers, viewport={"width": 1100, "height": 760})
        page = context.new_page()

        def route_js(route):
            hits["app.js"] += 1
            route.fulfill(status=200, content_type="text/javascript", body=APP_JS.read_text())

        def route_raw(route):
            path = parse_qs(urlparse(route.request.url).query).get("path", [""])[0]
            if path == IMAGE_PATH:
                hits["missing_source"] += 1
                route.fulfill(status=404)
            else:
                route.continue_()

        page.route("**/static/js/app.js*", route_js)
        page.route("**/api/files/raw?**", route_raw)
        page.on(
            "response",
            lambda response: hits.__setitem__(
                "full_log", hits["full_log"] + (response.url.endswith(f"/api/logs/{RESULT_ID}"))
            ),
        )
        page.goto(BASE, wait_until="load")
        page.wait_for_function("() => typeof _restoreToolResultImage === 'function'")
        page.wait_for_function("() => typeof selectedAgent !== 'undefined' && selectedAgent !== null")
        page.evaluate(
            """async ([toolId, resultId]) => {
                selectedAgent = null;
                if (eventSource) { eventSource.close(); eventSource = null; }
                window.compactMode = false;
                $('#chat').innerHTML = '';
                const tool = await api(`/api/logs/${toolId}`);
                const result = await api(`/api/logs/${resultId}`);
                const clipped = result.content.slice(0, 16384);
                addChatEntry(tool.type, tool.content, tool.ts, null, tool);
                addChatEntry(result.type, clipped, result.ts, null, {
                    ...result,
                    content: clipped,
                    trunc: new TextEncoder().encode(result.content).length,
                });
            }""",
            [TOOL_ID, RESULT_ID],
        )
        page.wait_for_function("() => $('#chat img')?.naturalWidth > 0")
        observed = page.evaluate(
            """() => ({
                width: $('#chat img').naturalWidth,
                height: $('#chat img').naturalHeight,
                placeholder: $('#chat').textContent.includes('[Image result]'),
                source: $('#chat img').src.slice(0, 32),
            })"""
        )
        # One full-log request builds the truncated fixture; the second is the fallback itself.
        if hits != {"app.js": 1, "missing_source": 1, "full_log": 2}:
            raise RuntimeError(f"unexpected request path: {hits}")
        if observed["placeholder"] or observed["width"] <= 0:
            raise RuntimeError(f"image was not restored: {observed}")
        page.locator("#chat").screenshot(path=OUT)
        print(f"hits={hits}")
        print(f"image={observed}")
        print(f"screenshot={OUT}")
        browser.close()


if __name__ == "__main__":
    main()
