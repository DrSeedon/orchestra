#!/usr/bin/env python3
"""#136 — просмотр .json показывает то, что в файле, без округления длинных чисел.

Живой :8888 отдаёт статику из ОСНОВНОГО чекаута, поэтому подменяем ОБА файла из worktree
(`app.js` и `utils.js` — формат-функция живёт во втором) и печатаем счётчики срабатываний.
Факт применения — `typeof _prettyJsonText` в рантайме.

Сверка посимвольная: текст из DOM разбирается обратно и сравнивается с файлом по каждому
числовому литералу, плюс печатается первое расхождение, если оно есть.

Запуск:  python3 docs/tasks/136/verify-json.py
"""
import json
import re

from playwright.sync_api import sync_playwright

WT = "/home/kesha/orchestra/worktrees/home-kesha-orchestra/frontend"
BASE = "http://127.0.0.1:8888"
BIG = f"{WT}/docs/tasks/136/bigint-sample.json"
PLAIN = f"{WT}/docs/tasks/136/plain-sample.json"

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env")
           if "=" in l and not l.startswith("#"))
USER, PWD = env["DASHBOARD_USER"].strip(), env["DASHBOARD_PASSWORD"].strip()

hits = {"app.js": 0, "utils.js": 0}


def literals(text):
    """Все числовые литералы вне строк — то, что юзер скопирует из окна."""
    without_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    return re.findall(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", without_strings)


def open_json(page, path):
    page.evaluate("path => openFilePreview(path)", path)
    page.wait_for_selector("#file-preview-modal code.language-json", timeout=15000)
    page.wait_for_function(
        "() => document.querySelector('#file-preview-modal code.language-json')"
        ".textContent.length > 10", timeout=15000)
    return page.evaluate(
        "() => document.querySelector('#file-preview-modal code.language-json').textContent")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))

        def sub(name):
            def handler(route):
                hits[name] += 1
                route.fulfill(status=200,
                              content_type="application/javascript; charset=utf-8",
                              body=open(f"{WT}/app/static/js/{name}", encoding="utf-8").read())
            return handler

        page.route("**/static/js/app.js*", sub("app.js"))
        page.route("**/static/js/utils.js*", sub("utils.js"))

        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.fill('input[name="username"]', USER)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#chat-input", timeout=20000)

        applied = page.evaluate("() => typeof _prettyJsonText")
        print(f"перехваты: {hits};  typeof _prettyJsonText = {applied}")
        assert applied == "function", "подмена не применилась — мерили бы прод"

        checks = []

        # --- 1. файл с 19-значными числами ---
        shown = open_json(page, BIG)
        on_disk = open(BIG, encoding="utf-8").read()
        print("\n--- .json с длинными id, текст в окне:")
        print(shown)
        disk_lits, shown_lits = literals(on_disk), literals(shown)
        print(f"\nчисловых литералов: в файле {len(disk_lits)}, в окне {len(shown_lits)}")
        bad = [(a, b) for a, b in zip(disk_lits, shown_lits) if a != b]
        print(f"расхождений: {bad or 'нет'}")
        checks.append(("каждый числовой литерал совпал с файлом",
                       disk_lits == shown_lits and len(disk_lits) >= 6))
        checks.append(("19-значный id показан целиком",
                       "1917704623170653147" in shown
                       and "1917704623170653200" not in shown))
        checks.append(("окно — валидный json тех же значений",
                       json.loads(shown) == json.loads(on_disk)))
        page.screenshot(path=f"{WT}/docs/tasks/136/json-bigint.png")
        page.keyboard.press("Escape")

        # --- 2. обычный json: раскладка ровно та же, что раньше ---
        shown_plain = open_json(page, PLAIN)
        plain_disk = open(PLAIN, encoding="utf-8").read()
        old_way = json.dumps(json.loads(plain_disk), indent=2, ensure_ascii=False)
        print("\n--- обычный .json, текст в окне:")
        print(shown_plain)
        first_diff = next((i for i, (a, b) in enumerate(zip(shown_plain, old_way)) if a != b),
                          None if len(shown_plain) == len(old_way) else min(
                              len(shown_plain), len(old_way)))
        print(f"первое расхождение с прежним выводом: {first_diff}")
        checks.append(("обычный json выглядит как раньше", shown_plain == old_way))
        page.screenshot(path=f"{WT}/docs/tasks/136/json-plain.png")

        print(f"\nперехваты: {hits};  ошибок в консоли: {errors or 'нет'}")
        checks.append(("нет ошибок в консоли", not errors))

        print()
        for name, ok in checks:
            print(f"  {'OK  ' if ok else 'FAIL'} {name}")
        print("\nИТОГ:", "всё зелёное" if all(ok for _, ok in checks) else "ЕСТЬ ПАДЕНИЯ")
        browser.close()


if __name__ == "__main__":
    main()
