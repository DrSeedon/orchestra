#!/usr/bin/env python3
"""#74 — маркер обрезки виден, кнопка приносит строку целиком.

Живой :8888 отдаёт СТАРЫЙ питон (рестарта не было), поэтому серверную половину подменяем
перехватом: страница истории возвращается обрезанной с `trunc`, а `/api/logs/<id>` —
целой. Проверяется клиент: виден ли маркер, не рисуется ли битая картинка, заменяется ли
узел на полный после нажатия. Счётчики срабатывания перехвата печатаются рядом.

Запуск:  python3 verify-trunc.py branch|main
"""
import json
import subprocess
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
AGENT = "back"
CAP = 1024
FULL = "ПОЛНАЯ-СТРОКА " * 4000            # ~56 КБ, «оригинал» строки
SHOWN = FULL[:CAP]

variant = sys.argv[1] if len(sys.argv) > 1 else "branch"
if variant == "branch":
    JS = open(f"{WT}/app/static/js/app.js").read()
else:
    JS = subprocess.run(["git", "-C", WT, "show", f"{variant}:app/static/js/app.js"],
                        capture_output=True, text=True, check=True).stdout
CSS = open(f"{WT}/app/static/css/style.css").read()

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

hits = {"js": 0, "css": 0, "full": 0}
FAT_ID = 10 ** 8   # заведомо больше любого живого id: строка должна оказаться последней


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        def route_css(route):
            hits["css"] += 1
            route.fulfill(status=200, content_type="text/css; charset=utf-8", body=CSS)

        def route_full(route):
            hits["full"] += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"id": FAT_ID, "session_id": "s", "ts": "2026-08-04T10:00:00+00:00",
                 "type": "text", "content": FULL, "event_id": ""}))

        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)
        page.route(lambda u: urlparse(u).path.endswith("/static/css/style.css"), route_css)
        page.route(f"**/api/logs/{FAT_ID}", route_full)

        page.on("console", lambda m: m.type in ("error", "warning") and print(f"   [console:{m.type}] {m.text[:160]}"))
        page.on("pageerror", lambda e: print(f"   [pageerror] {e}"))
        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.click(f"#agent-list >> text={AGENT}", timeout=20000)
        page.wait_for_timeout(6000)

        # Обрезанную строку рисуем ТЕМ ЖЕ вызовом, которым рисуется вся история
        # (_renderHistory: addChatEntry(type, content, ts, null, row)).
        page.evaluate("""([shown, len, id]) => {
            addChatEntry('text', shown, '2026-08-04T10:00:00+00:00', null,
                         {id, session_id: _chatSessionId, type: 'text', content: shown,
                          ts: '2026-08-04T10:00:00+00:00', trunc: len});
        }""", [SHOWN, len(FULL.encode()), FAT_ID])
        page.wait_for_timeout(500)

        dbg = page.evaluate("() => ({узлов: document.querySelectorAll('#chat > *').length,"
                            " сЛогId: document.querySelectorAll('#chat [data-chat-log-id]').length,"
                            " максId: Math.max(0, ...[...document.querySelectorAll('#chat [data-chat-log-id]')]"
                            ".map(n => Number(n.dataset.chatLogId)))})")
        print(f"   отладка: {dbg}")
        marker = page.locator(".trunc-notice")
        print(f"вариант: {variant};  подмена app.js {hits['js']}x, style.css {hits['css']}x, "
              f"страница чата загружена, узлов с id: {dbg['сЛогId']}")
        print(f"маркеров обрезки на странице: {marker.count()}")
        if marker.count():
            print(f"   текст: {marker.first.inner_text().strip()}")
            box = marker.first.bounding_box()
            print(f"   виден: {marker.first.is_visible()}, размер {box['width']:.0f}×{box['height']:.0f} px")
            page.screenshot(path=f"{WT}/docs/tasks/74/trunc-notice.png",
                            clip={"x": box["x"] - 260, "y": box["y"] - 90,
                                  "width": 820, "height": 190})

        shown_len = page.evaluate("() => { const n = document.querySelector('[data-chat-log-id=\"%d\"]');"
                                  " return n ? n.innerText.length : -1; }" % FAT_ID)
        if marker.count():
            page.locator(".trunc-load").first.click()
            page.wait_for_timeout(2500)
        full_len = page.evaluate("() => { const n = document.querySelector('[data-chat-log-id=\"%d\"]');"
                                 " return n ? n.innerText.length : -1; }" % FAT_ID)
        print(f"запрошена строка целиком: {hits['full']}x")
        print(f"символов в узле: до нажатия {shown_len}, после {full_len}")
        print(f"маркеров после нажатия: {page.locator('.trunc-notice').count()}")
        browser.close()


main()
