#!/usr/bin/env python3
"""#72 — форма запросов истории: что просит клиент и сколько строк в итоге показывает.

Живой :8888 (питон там СТАРЫЙ — рестарта не было), `app.js` подменён из worktree.
Проверяется поведение КЛИЕНТА: сколько запросов, с какими параметрами, сколько строк
нарисовано. Байты по проводу тут не мерить — локальный сервер отдаёт без gzip, цифры
через домен лежат в docs/tasks/72/report.md.

Запуск:  python3 verify-chunks.py branch|main
"""
import subprocess
import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
AGENT = "back"

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
sync_calls, hist_calls = [], []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)

        def on_request(req):
            path = urlparse(req.url).path
            q = parse_qs(urlparse(req.url).query)
            if path == "/api/logs/sync":
                sync_calls.append({k: v[0] for k, v in q.items()})
            elif path.startswith("/api/sessions/") and path.endswith("/logs"):
                hist_calls.append({"agent": path.split("/")[3],
                                   "limit": q.get("limit", ["—"])[0],
                                   "max_bytes": q.get("max_bytes", ["нет"])[0]})

        page.on("request", on_request)

        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.click(f"#agent-list >> text={AGENT}", timeout=20000)
        page.wait_for_timeout(9000)   # добор идёт после первого кадра, порции последовательные

        rows = page.evaluate("() => (chatLogs[selectedAgent] || {}).initialCount || 0")
        agent = page.evaluate("() => selectedAgent")
        newest = page.evaluate("() => (chatLogs[selectedAgent] || {}).lastId || 0")

        first_phase = [dict(h) for h in hist_calls if h["agent"] == AGENT]
        # F5: зеркало обязано отдать ТУ ЖЕ историю, включая самый свежий кусок. Раньше его
        # привозила холодная синхронизация; теперь его пишет тот, кто скачал.
        hist_calls.clear()
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#agent-list", timeout=20000)
        page.wait_for_timeout(9000)
        rows2 = page.evaluate("() => (chatLogs[selectedAgent] || {}).initialCount || 0")
        newest2 = page.evaluate("() => (chatLogs[selectedAgent] || {}).lastId || 0")
        after_reload = len([h for h in hist_calls if h["agent"] == AGENT])
        browser.close()

    print(f"вариант: {variant};  подмена app.js: {hits['js']}x;  открытый агент: {agent}")
    print(f"холодная синхронизация: {sync_calls}")
    mine = first_phase
    print(f"запросов истории по {AGENT}: {len(mine)}")
    for h in mine:
        print(f"   limit={h['limit']}, max_bytes={h['max_bytes']}")
    print(f"строк истории нарисовано: {rows}, самая свежая строка id={newest}")
    print(f"после F5: строк {rows2}, самая свежая id={newest2}, запросов истории {after_reload}")


main()
