#!/usr/bin/env python3
"""#74/#66 на ЖИВОМ сервере — без единой подмены.

Рестарт 11:44 (сборка b4137bca) — значит сервер отдаёт `cap`, `trunc` и `/api/logs/<id>`
сам. `page.route` здесь НЕ используется намеренно: весь смысл проверки в том, что работает
выкаченное, а не мой worktree. Открываем чат, у которого жирная строка попадает в страницу
(`seo-cro`, строка 451 847 Б, после неё всего 65 строк).

Запуск:  python3 verify-live.py
"""
import json
import urllib.parse
import urllib.request
import http.cookiejar

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
BASE = "http://127.0.0.1:8888"
PROJECT = "seedon"
AGENT = "seo-cro"

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

# --- статусы сессий: есть ли живой случай broken (#66) ---
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open(f"{BASE}/login", urllib.parse.urlencode({"username": USER, "password": PWD}).encode())
statuses = {}
for scope in ("/home/kesha/orchestra", "/home/kesha/projects/seedon"):
    data = json.load(op.open(f"{BASE}/api/sessions?scope={urllib.parse.quote(scope)}"))
    for s in (data if isinstance(data, list) else data.get("sessions", [])):
        statuses.setdefault(s.get("status"), []).append(s["name"])
print("статусы живых сессий:", {k: len(v) for k, v in statuses.items()})
print("сессии в статусе broken:", statuses.get("broken", []) or "нет ни одной")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:120]))

        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#agent-list", timeout=20000)
        page.click(f"#orch-tabs >> text={PROJECT}", timeout=20000)
        page.wait_for_timeout(2000)
        page.click(f"#agent-list >> text={AGENT}", timeout=20000)
        page.wait_for_timeout(12000)      # добор идёт порциями, последовательно

        build = page.evaluate("() => document.body.dataset.build")
        marker = page.locator(".trunc-notice")
        print(f"\nсборка на странице: {build};  ошибок в консоли: {errors or 'нет'}")
        print(f"маркеров обрезки в чате {AGENT}: {marker.count()}")
        if not marker.count():
            browser.close()
            return
        print(f"   текст: {marker.first.inner_text().strip()}")

        node = marker.first.locator("xpath=..")
        node.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        box = marker.first.bounding_box()
        page.screenshot(path=f"{WT}/docs/tasks/74/live-trunc-notice.png",
                        clip={"x": box["x"] - 300, "y": max(0, box["y"] - 220),
                              "width": 900, "height": 320})
        # Картинки считаем по ВСЕМУ чату: обрезанный tool_result рисуется плашкой в своём
        # узле, а полный вливается в карточку инструмента и своего узла не создаёт.
        SHOT = """() => {
            const imgs = [...document.querySelectorAll('#chat img')];
            return {картинок: imgs.length,
                    битых: imgs.filter(i => i.complete && i.naturalWidth === 0).length,
                    размеры: imgs.map(i => `${i.naturalWidth}×${i.naturalHeight}`).slice(-3)};
        }"""
        before = page.evaluate(SHOT)
        print(f"   до нажатия: {before}")

        page.locator(".trunc-load").first.click()
        page.wait_for_timeout(6000)
        after = page.evaluate(SHOT)
        print(f"   после нажатия: {after}")
        print(f"   маркеров осталось: {page.locator('.trunc-notice').count()};  "
              f"ошибок в консоли: {errors or 'нет'}")
        page.screenshot(path=f"{WT}/docs/tasks/74/live-trunc-loaded.png",
                        clip={"x": 250, "y": 100, "width": 950, "height": 700})
        browser.close()


main()
