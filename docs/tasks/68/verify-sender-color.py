#!/usr/bin/env python3
"""#68 — цвет подписи «<кто> → <кому>» при позднем списке агентов.

Воспроизведение окна «история есть, агентов ещё нет» детерминированное: первые
STRIP_SECONDS секунд из ответа /api/sessions вырезается поле color (список рисуется,
агент выбирается, но agentColors пуст), дальше ответ идёт как есть.

Запуск:  python3 verify-sender-color.py branch|main
"""
import json
import subprocess
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
AGENT = "Orchestra-orchestrator"  # его чат содержит [from:<worker>] — у воркеров есть color (у оркестраторов color="")
STRIP_SECONDS = 12.0
GREY = "rgb(100, 116, 139)"

variant = sys.argv[1] if len(sys.argv) > 1 else "branch"
if variant == "branch":
    JS = open(f"{WT}/app/static/js/app.js").read()
else:
    JS = subprocess.run(["git", "-C", WT, "show", f"{variant}:app/static/js/app.js"],
                        capture_output=True, text=True, check=True).stdout

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER = env["DASHBOARD_USER"].strip()
PWD = env["DASHBOARD_PASSWORD"].strip()

hits = {"js": 0, "sessions": 0, "stripped": 0}
t0 = time.time()

PROBE = """() => {
  return [...document.querySelectorAll('#chat div.text-xs')]
    .filter(d => /^[A-Za-z0-9_.-]+ → /.test(d.textContent.trim()) && d.children.length === 0)
    .slice(0, 3)
    .map(d => getComputedStyle(d).color + '  ' + d.textContent.trim().slice(0, 40));
}"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        def route_sessions(route):
            hits["sessions"] += 1
            resp = route.fetch()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("sessions", [])
            if time.time() - t0 < STRIP_SECONDS:
                hits["stripped"] += 1
                for s in items:
                    s.pop("color", None)
            route.fulfill(status=resp.status, content_type="application/json", body=json.dumps(data))

        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)
        page.route(lambda u: urlparse(u).path == "/api/sessions", route_sessions)

        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.click(f"#agent-list >> text={AGENT}", timeout=20000)

        page.wait_for_function(f"({PROBE})().length > 0", timeout=30000)
        before = page.evaluate(PROBE)
        print(f"[t={time.time()-t0:.1f}s] agentColors пуст (color вырезан), подписи:")
        for x in before:
            print("   ", x)

        # ждём, пока пройдёт окно вырезания и приедет ответ с цветами
        page.wait_for_timeout(int((STRIP_SECONDS - (time.time() - t0) + 6) * 1000))
        after = page.evaluate(PROBE)
        print(f"[t={time.time()-t0:.1f}s] цвета агентов приехали, те же подписи:")
        for x in after:
            print("   ", x)

        page.evaluate("""() => {
            const d = [...document.querySelectorAll('#chat div.text-xs')]
                .filter(d => /^[A-Za-z0-9_.-]+ → /.test(d.textContent.trim()) && d.children.length === 0)[0];
            if (d) d.scrollIntoView({block: 'center'});
        }""")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{WT}/docs/tasks/68/sender-color-{variant}.png")
        browser.close()

    print(f"\nвариант: {variant}")
    print(f"подмена app.js сработала: {hits['js']}x;  /api/sessions: {hits['sessions']}x, "
          f"из них с вырезанным color: {hits['stripped']}x")
    grey_before = sum(1 for x in before if x.startswith(GREY))
    grey_after = sum(1 for x in after if x.startswith(GREY))
    print(f"серых подписей ({GREY}): до {grey_before}/{len(before)}, после {grey_after}/{len(after)}")


main()
