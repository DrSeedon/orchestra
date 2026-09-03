#!/usr/bin/env python3
"""#75 — таймаут 3.5 → 2 с: первый экран после обрыва и отсутствие резни здоровых ответов.

Две части, обе числом:
  A. Первый экран, когда первая попытка встала (ровно случай юзера: wire=0 Б dur=таймаут,
     повтор успешен). Часы БРАУЗЕРНЫЕ (`performance.now()` в обёртке над fetch и в
     MutationObserver): хостовой секундомер на этой машине непригоден — при LA 8 он дал
     ветке 6.25 с против 4.30 у main, то есть шум больше измеряемой величины. Каждый
     вариант гоняется трижды, печатается медиана.
  B. Обычная работа без обрывов: сколько раз `api()` уходил на повтор. Повтор он печатает
     в консоль сам, поэтому считаем предупреждения, а не гадаем по числу запросов.

Запуск:  python3 verify-timeout.py branch|main
"""
import re
import subprocess
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
AGENT = "back"
WINDOW_S = 30

variant = sys.argv[1] if len(sys.argv) > 1 else "branch"
if variant == "branch":
    JS = open(f"{WT}/app/static/js/app.js").read()
else:
    JS = subprocess.run(["git", "-C", WT, "show", f"{variant}:app/static/js/app.js"],
                        capture_output=True, text=True, check=True).stdout
TIMEOUT_MS = int(re.search(r"_API_TIMEOUT_MS = (\d+)", JS).group(1))

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()


PROBE_INIT = """
window.__probe = {calls: [], firstPaint: null};
const _f = window.fetch;
window.fetch = async function (...args) {
    const url = String(args[0] && args[0].url || args[0] || '');
    const rec = {url, start: performance.now(), end: null, failed: false};
    if (url.includes('/api/')) window.__probe.calls.push(rec);
    try {
        const r = await _f.apply(this, args);
        rec.end = performance.now();
        return r;
    } catch (e) {
        rec.end = performance.now();
        rec.failed = true;
        throw e;
    }
};
// Опрос, а не MutationObserver: init-скрипт выполняется ДО появления documentElement,
// и observe() на нём падает — в первом прогоне firstPaint из-за этого не заполнился ни разу.
const _tick = setInterval(() => {
    const list = document.getElementById('agent-list');
    if (list && list.children.length > 0) {
        window.__probe.firstPaint = performance.now();
        clearInterval(_tick);
    }
}, 30);
"""


def run(hang_first_sessions):
    hits = {"js": 0, "sessions": 0}
    retries = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def route_js(route):
            hits["js"] += 1
            route.fulfill(status=200, content_type="application/javascript; charset=utf-8", body=JS)

        def route_sessions(route):
            hits["sessions"] += 1
            if hang_first_sessions and hits["sessions"] == 1:
                return          # первая попытка встала намертво — посредник у юзера делает так же
            route.continue_()

        page.add_init_script(PROBE_INIT)
        page.route(lambda u: urlparse(u).path.endswith("/static/js/app.js"), route_js)
        page.route(lambda u: urlparse(u).path == "/api/sessions", route_sessions)
        page.on("console", lambda m: "попытка" in m.text and retries.append(m.text[:110]))

        page.goto("http://127.0.0.1:8888/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        t0 = time.time()
        page.click('button[type="submit"]')
        page.wait_for_function("() => document.getElementById('agent-list')"
                               " && document.getElementById('agent-list').children.length > 0",
                               timeout=40000)
        # Отметка ставится опросом раз в 30 мс — даём ей долиться, иначе поле пустое просто
        # потому, что тик не успел, и замер молча теряется.
        page.wait_for_function("() => window.__probe.firstPaint !== null", timeout=5000)
        probe = page.evaluate("() => window.__probe")
        if not hang_first_sessions:
            page.click(f"#agent-list >> text={AGENT}", timeout=20000)
            page.wait_for_timeout(WINDOW_S * 1000)
        browser.close()
    calls = [c for c in probe["calls"] if "/api/sessions?" in c["url"]]
    all_calls = probe["calls"]
    hung = next((c for c in calls if c["failed"]), None)
    ok = next((c for c in calls if not c["failed"] and c["end"]), None)
    return {
        "оборвалась через": round((hung["end"] - hung["start"]) / 1000, 2) if hung else None,
        "данные пришли через": round((ok["end"] - hung["start"]) / 1000, 2) if (hung and ok) else None,
        "первый экран": round(probe["firstPaint"] / 1000, 2) if probe["firstPaint"] else None,
        "самый долгий api": round(max((c["end"] - c["start"] for c in all_calls
                                       if c["end"] and not c["failed"]), default=0)),
    }, hits, retries


import statistics

runs = [run(hang_first_sessions=True) for _ in range(3)]
print(f"вариант: {variant} (_API_TIMEOUT_MS={TIMEOUT_MS});  подмена app.js "
      f"{sum(h['js'] for _, h, _ in runs)}x за 3 прогона")
print(f"A. первая попытка /api/sessions встала намертво; попыток "
      f"{[h['sessions'] for _, h, _ in runs]}, часы браузерные, медиана трёх прогонов:")
for key in ("оборвалась через", "данные пришли через", "первый экран"):
    vals = [m[key] for m, _, _ in runs if m[key] is not None]
    if not vals:
        print(f"   {key:22s} НЕТ ДАННЫХ — зонд не заполнился, замер недействителен")
        continue
    print(f"   {key:22s} {statistics.median(vals):5.2f} с   (прогоны {vals})")

m, hits2, retries = run(hang_first_sessions=False)
print(f"B. без обрывов, окно {WINDOW_S} с после открытия чата {AGENT}: "
      f"повторов api() {len(retries)}" + (f" — {retries}" if retries else " (ни один здоровый ответ не срезан)"))
print(f"   самый долгий успешный api-запрос окна: {m['самый долгий api']} мс "
      f"(потолок {TIMEOUT_MS} мс). Это НАША сторона, у юзера канал другой — его цифры от perf.")
