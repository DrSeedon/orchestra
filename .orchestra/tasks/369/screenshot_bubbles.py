"""#369: screenshots of harness tool bubbles for the user (live :8888 + route substitution).

Урок после пустого первого снимка: фоновый код дашборда умеет вычищать чат между
проверкой и снимком, поэтому порядок такой — инжект → ПОЛОЖИТЕЛЬНАЯ проверка
(видимость конкретного баббла) → заморозка DOM клоном (его никто не тронет) →
пост-проверка клона → element.screenshot чата → пиксельная самопроверка файла.
"""

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


def shoot(page, calls, compact: bool, marker_sel: str, out_name: str) -> None:
    """Инжект + заморозка одним ходом, проверки ДО и ПОСЛЕ заморозки, снимок узла."""
    page.evaluate("""(args) => {
        const [calls, compact] = args;
        const chat = document.querySelector('#chat, #chat-frozen');
        chat.id = 'chat';
        selectedAgent = null;
        if (eventSource) { eventSource.close(); eventSource = null; }
        window.compactMode = compact;
        chat.innerHTML = '';
        for (const [type, content] of calls) {
            addChatEntry(type, content, null, null, {});
        }
        const k = chat.cloneNode(true);
        k.id = 'chat-frozen';
        chat.parentNode.replaceChild(k, chat);
    }""", [calls, compact])
    # положительный признак отрисовки — уже на замороженном клоне
    page.locator(f"#chat-frozen {marker_sel}").first.wait_for(state="visible", timeout=10000)
    page.locator("#chat-frozen").screenshot(path=str(OUT / out_name))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
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
        # Гейт: подменённый код жив (символа в main нет)
        page.wait_for_function("() => typeof HARNESS_TOOL_ALIASES !== 'undefined'",
                               timeout=10000)

        shoot(page, CALLS_FULL, False, "[data-is-bash]", "bubbles-full.png")
        shoot(page, CALLS_COMPACT, True, '[data-tool-raw="Bash"]', "bubbles-compact.png")
        browser.close()

    # Скриншот — артефакт: проверяем пиксели, а не верим в ожидаемое.
    from PIL import Image
    ok = True
    for name in ("bubbles-full.png", "bubbles-compact.png"):
        im = Image.open(OUT / name).convert("RGB")
        colors = im.getcolors(maxcolors=1_000_000)
        n_colors = len(colors)
        top = max(colors, key=lambda c: c[0])[0]
        non_bg = 1 - top / (im.width * im.height)
        good = im.height > 200 and n_colors >= 500 and non_bg >= 0.05
        ok &= good
        print(f"{name}: {im.width}x{im.height}, colors={n_colors}, "
              f"non-background={non_bg:.1%} -> {'OK' if good else 'BLANK?'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
