"""Browser acceptance and before/after switch timing for #185."""
from pathlib import Path
import re
import statistics
import subprocess

from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("chat-timeline.png")
BASE_URL = "http://127.0.0.1:8888"
TARGET_SCOPE = "/home/kesha/projects/seedon"
TARGET_AGENT = "seedon-orchestrator"
RUNS = 5


def at_head(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout


def chat_fragment(template: str) -> str:
    match = re.search(
        r'                <div id="chat".*?\n'
        r'.*?                <button id="chat-jump-latest".*?</button>',
        template,
        re.S,
    )
    if not match:
        raise RuntimeError("chat fragment not found")
    return match.group(0)


def main() -> None:
    env = dotenv_values("/home/kesha/orchestra/.env")
    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
    old_js = at_head("app/static/js/app.js")
    old_css = at_head("app/static/css/style.css")
    old_template = at_head("app/templates/dashboard.html")
    new_js = (ROOT / "app/static/js/app.js").read_text()
    new_css = (ROOT / "app/static/css/style.css").read_text()
    new_template = (ROOT / "app/templates/dashboard.html").read_text()
    old_fragment = chat_fragment(old_template)
    new_fragment = chat_fragment(new_template)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])

        def open_variant(current: bool):
            context = browser.new_context(extra_http_headers=headers, viewport={"width": 1440, "height": 900})
            page = context.new_page()
            hits = {"js": 0, "css": 0, "document": 0}

            def route_asset(route):
                path = route.request.url.split("?", 1)[0]
                if path.endswith("/static/js/app.js"):
                    hits["js"] += 1
                    route.fulfill(content_type="text/javascript", body=new_js if current else old_js)
                elif path.endswith("/static/css/style.css"):
                    hits["css"] += 1
                    route.fulfill(content_type="text/css", body=new_css if current else old_css)
                else:
                    route.continue_()

            def route_document(route):
                response = route.fetch()
                body = response.text()
                if current and old_fragment in body:
                    body = body.replace(old_fragment, new_fragment, 1)
                    hits["document"] += 1
                route.fulfill(response=response, body=body)

            page.route("**/static/js/app.js*", route_asset)
            page.route("**/static/css/style.css*", route_asset)
            page.route(BASE_URL, route_document)
            page.goto(BASE_URL, wait_until="load")
            page.wait_for_function("typeof _showChatFor === 'function'")
            if current:
                page.wait_for_selector("#chat-timeline")
                page.wait_for_function("typeof _jumpChatTimelineUser === 'function'")
            return context, page, hits

        timings = {"before": [], "after": []}
        screenshot_page = None
        screenshot_context = None
        for current, label in [(False, "before"), (True, "after")]:
            context, page, hits = open_variant(current)
            option = page.locator(f'#orch-picker option[data-name="{TARGET_AGENT}"]')
            option.wait_for(state="attached")
            page.evaluate(
                """scope => {
                    const picker = $('#orch-picker');
                    picker.value = scope;
                    picker.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                TARGET_SCOPE,
            )
            page.wait_for_function(
                "([name]) => selectedAgent === name && !_chatLoading && $('#chat').children.length > 0",
                arg=[TARGET_AGENT],
            )
            fallback = page.evaluate("() => [...document.querySelectorAll('.agent-item .text-xs.font-medium')].map(e => e.textContent).find(n => n && n !== selectedAgent)")
            if not fallback:
                raise RuntimeError("no second agent for switch timing")

            for _ in range(RUNS):
                page.evaluate("name => selectAgent(name)", fallback)
                page.wait_for_function(
                    "name => selectedAgent === name && !_chatLoading && $('#chat').children.length > 0",
                    arg=fallback,
                )
                elapsed = page.evaluate(
                    """async name => {
                        const started = performance.now();
                        await selectAgent(name);
                        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                        return performance.now() - started;
                    }""",
                    TARGET_AGENT,
                )
                timings[label].append(round(elapsed, 1))

            print(f"{label}: hits={hits}, switch_ms={timings[label]}")
            if current:
                page.wait_for_function(
                    "() => (chatLogs[selectedAgent]?.initialCount || 0) >= 100",
                    timeout=30_000,
                )
                page.wait_for_function("() => document.querySelectorAll('#chat-timeline-track .chat-timeline-marker').length >= 20")
                user_markers = page.locator("#chat-timeline-track .is-user")
                if user_markers.count() < 2:
                    raise RuntimeError("target chat has fewer than two human messages in the loaded page")
                user_markers.nth(0).click()
                page.wait_for_function(
                    """() => {
                        const marker = $('#chat-timeline-track .is-active');
                        const node = [...$('#chat').children].find(child => child._chatTimelineMarker === marker);
                        const chat = $('#chat').getBoundingClientRect();
                        const rect = node?.getBoundingClientRect();
                        return !!rect && rect.top < chat.bottom && rect.bottom > chat.top;
                    }"""
                )
                clicked = page.evaluate(
                    """() => {
                        const marker = $('#chat-timeline-track .is-active');
                        const node = [...$('#chat').children].find(child => child._chatTimelineMarker === marker);
                        const chat = $('#chat').getBoundingClientRect();
                        const rect = node?.getBoundingClientRect();
                        return {kind: node?.dataset.chatNavKind, visible: !!rect && rect.top < chat.bottom && rect.bottom > chat.top};
                    }"""
                )
                before_active = page.evaluate("() => [...$('#chat-timeline-track').children].indexOf($('#chat-timeline-track .is-active'))")
                page.locator("#chat-user-next").click()
                page.wait_for_timeout(450)
                after_active = page.evaluate("() => [...$('#chat-timeline-track').children].indexOf($('#chat-timeline-track .is-active'))")
                print(
                    "acceptance:",
                    {"runtime": page.evaluate("() => typeof _jumpChatTimelineUser"),
                     "markers": page.locator("#chat-timeline-track .chat-timeline-marker").count(),
                     "user_markers": user_markers.count(), "clicked": clicked,
                     "sequential_indices": [before_active, after_active]},
                )
                screenshot_page = page
                screenshot_context = context
            else:
                context.close()

        before = statistics.median(timings["before"])
        after = statistics.median(timings["after"])
        print(f"median: before={before:.1f} ms, after={after:.1f} ms, delta={after - before:+.1f} ms")
        screenshot_page.screenshot(path=OUT, full_page=True)
        print(f"screenshot: {OUT}")
        screenshot_context.close()
        browser.close()


if __name__ == "__main__":
    main()
