#!/usr/bin/env python3
"""#70 — повтор GET при обрыве. Проверка ЧИСЛОМ ПОПЫТОК, не флагом занятости.

Живой :8888, `app.js` подменён из worktree, HTML дашборда (он приезжает ответом на POST
/login) переписан, чтобы в нём был `#net-fail-banner` из моей ветки. Зонды дёргают
`window.api(...)` напрямую и считают, сколько раз запрос реально ушёл в сеть.

Запуск:  python3 verify-retry.py branch|main
"""
import json
import subprocess
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
BANNER = ('<div id="net-fail-banner" class="hidden items-center justify-center gap-2 px-4 py-2 '
          'bg-red-500/15 border-b border-red-500/40 text-red-200 text-xs"></div>')

variant = sys.argv[1] if len(sys.argv) > 1 else "branch"
if variant == "branch":
    JS = open(f"{WT}/app/static/js/app.js").read()
else:
    JS = subprocess.run(["git", "-C", WT, "show", f"{variant}:app/static/js/app.js"],
                        capture_output=True, text=True, check=True).stdout

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

hits = {"js": 0, "html": 0, "hang": 0, "flaky": 0, "err500": 0, "post": 0, "sessions": 0}


def probe(page, url, method="GET"):
    """Зовёт window.api и возвращает (исход, секунды)."""
    return page.evaluate("""async ([url, method]) => {
        const t = performance.now();
        try {
            await api(url, method === 'GET' ? {} : { method, body: '{}' });
            return ['ok', (performance.now() - t) / 1000];
        } catch (e) {
            return [e.name + ': ' + String(e.message).slice(0, 60), (performance.now() - t) / 1000];
        }
    }""", [url, method])


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        def route_html(route):
            # HTML дашборда приезжает ответом на POST /login — фильтровать по URL нельзя,
            # поэтому переписываем любой документ, в котором нашёлся нужный якорь.
            resp = route.fetch()
            body = resp.text()
            anchor = '<div id="rate-limit-banner"'
            if anchor in body and 'id="net-fail-banner"' not in body:
                body = body.replace(anchor, BANNER + "\n    " + anchor, 1)
                hits["html"] += 1
            route.fulfill(status=resp.status, headers={"content-type": "text/html; charset=utf-8"}, body=body)

        def route_hang(route):
            hits["hang"] += 1  # никогда не отвечаем — ровно то, что делает посредник у юзера

        def route_flaky(route):
            hits["flaky"] += 1
            if hits["flaky"] == 1:
                return  # первая попытка виснет
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

        def route_500(route):
            hits["err500"] += 1
            route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')

        def route_post(route):
            hits["post"] += 1  # тоже виснет

        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)
        page.route(lambda u: urlparse(u).path in ("/", "/login"), route_html)
        page.route("**/api/probe-hang", route_hang)
        page.route("**/api/probe-flaky", route_flaky)
        page.route("**/api/probe-500", route_500)
        page.route("**/api/probe-post", route_post)

        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)

        print(f"вариант: {variant}")
        print(f"подмена app.js: {hits['js']}x, HTML с баннером переписан: {hits['html']}x")
        print(f"баннер в DOM: {page.locator('#net-fail-banner').count()}")

        r = probe(page, "/api/probe-hang")
        print(f"\n1. висящий GET       → попыток {hits['hang']}, {r[1]:.1f} с, исход {r[0]}")
        vis = page.evaluate("() => { const b = document.getElementById('net-fail-banner');"
                            " return b ? (b.classList.contains('hidden') ? 'скрыт' : b.textContent.trim().slice(0, 90)) : 'элемента нет'; }")
        print(f"   баннер после исчерпания: {vis}")
        page.screenshot(path=f"{WT}/docs/tasks/70/net-fail-banner-{variant}.png", clip={"x": 0, "y": 0, "width": 1400, "height": 120})

        r = probe(page, "/api/probe-flaky")
        print(f"2. обрыв, потом ответ → попыток {hits['flaky']}, {r[1]:.1f} с, исход {r[0]}")
        vis = page.evaluate("() => { const b = document.getElementById('net-fail-banner');"
                            " return b ? (b.classList.contains('hidden') ? 'скрыт' : 'виден') : 'элемента нет'; }")
        print(f"   баннер (он про ДРУГОЙ путь — успех его снимать не должен): {vis}")

        r = probe(page, "/api/probe-500")
        print(f"3. ответ 500          → попыток {hits['err500']}, {r[1]:.1f} с, исход {r[0]}")

        r = probe(page, "/api/probe-post", method="POST")
        print(f"4. висящий POST       → попыток {hits['post']}, {r[1]:.1f} с, исход {r[0]}")

        # 5. живой путь: /api/sessions висит 12 с — сколько раз цикл обновления успеет
        #    сходить в сеть за это окно (single-flight держит по одному запросу зараз)
        def route_sessions_hang(route):
            hits["sessions"] += 1

        sess_pred = lambda u: urlparse(u).path == "/api/sessions"
        page.route(sess_pred, route_sessions_hang)
        page.wait_for_timeout(12000)
        vis = page.evaluate("() => { const b = document.getElementById('net-fail-banner');"
                            " return b.classList.contains('hidden') ? 'скрыт' : 'виден'; }")
        print(f"\n5. /api/sessions висит 12 с → попыток {hits['sessions']}, баннер: {vis}")
        page.unroute(sess_pred, route_sessions_hang)
        page.wait_for_timeout(6000)
        vis = page.evaluate("() => { const b = document.getElementById('net-fail-banner');"
                            " return b.classList.contains('hidden') ? 'скрыт' : 'виден'; }")
        # баннер снимается ТОЛЬКО успешным ответом — значит цикл обновления жив
        print(f"   после снятия перехвата: баннер {vis}, узлов в списке агентов "
              f"{page.evaluate('() => document.getElementById(\'agent-list\').children.length')}")

        browser.close()


main()
