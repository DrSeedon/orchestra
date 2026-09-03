#!/usr/bin/env python3
"""#71 — сколько раз /api/orchestrators уходит в сеть за первые 20 с после логина.

Проверка ЧИСЛОМ ЗАПРОСОВ, не глазами. Живой :8888, `app.js` подменён из worktree,
счётчик подмены печатается рядом с результатом. Окно замера названо явно: круг опроса
идёт раз в 3 с, на другом окне те же числа выглядят иначе.

Запуск:  python3 verify-orch-throttle.py branch|main
"""
import subprocess
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
WINDOW_S = 20

variant = sys.argv[1] if len(sys.argv) > 1 else "branch"
if variant == "branch":
    JS = open(f"{WT}/app/static/js/app.js").read()
else:
    JS = subprocess.run(["git", "-C", WT, "show", f"{variant}:app/static/js/app.js"],
                        capture_output=True, text=True, check=True).stdout

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

hits = {"js": 0}
calls = []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)

        t0 = [0.0]
        page.on("request", lambda r: urlparse(r.url).path == "/api/orchestrators"
                and calls.append(round(time.time() - t0[0], 2)))

        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        t0[0] = time.time()
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.wait_for_timeout(WINDOW_S * 1000)
        agents = page.evaluate("() => document.getElementById('agent-list').children.length")
        tabs = page.evaluate("() => document.getElementById('orch-tabs').children.length")
        browser.close()

    print(f"вариант: {variant};  подмена app.js: {hits['js']}x")
    print(f"/api/orchestrators за {WINDOW_S} с от сабмита логина: {len(calls)} — на {calls} с")
    print(f"вкладок оркестраторов отрисовано: {tabs}, узлов в списке агентов: {agents}")


main()
