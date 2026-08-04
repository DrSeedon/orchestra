"""#47 — посмотреть ГЛАЗАМИ, как запись о недоставке выглядит в дашборде.

Живой :8888, app.js подменяется версией из ветки, ответ /api/logs/sync берётся из копии
живой БД и дополняется одной синтетической строкой типа `system` — той самой, которую
пишет `_record_undelivered_auto_report`. Скриншот кладётся рядом.

Запуск: uv run python docs/tasks/47/screenshot-record.py
"""
import asyncio, json, pathlib, subprocess, sys

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
APP_JS = ROOT / "app/static/js/app.js"
DB_COPY = pathlib.Path("/tmp/live_copy.db")
OUT = pathlib.Path(__file__).resolve().parent / "record-in-dashboard.png"
BASE = "http://127.0.0.1:8888"

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

if not DB_COPY.exists():
    subprocess.run(["sqlite3", "/home/kesha/orchestra/data/orchestra.db",
                    f".backup {DB_COPY}"], check=True)
sys.path.insert(0, str(ROOT))
import app.db as _db                                     # noqa: E402
_db.DB_PATH = DB_COPY
from app.db import get_logs_sync                         # noqa: E402

RECORD = (
    "[доставка] автоотчёт воркера «worker» не доставлен оркестратору «boss»: "
    "RuntimeError: auto-switch failed: branch 'adhoc-1785700000-1/boss' already exists "
    "(HEAD ac25033a, last commit 2026-08-04T06:43:09+02:00) — refusing to adopt someone "
    "else's history; a fresh branch was expected. Попытка уведомить отдельным сообщением: "
    "уведомить boss не удалось: та же причина. Автоматического повтора нет — воркер ждёт "
    "продолжения."
)


async def main():
    data = get_logs_sync(after_id=0, tail=20, cap=16384)
    target = data["logs"][-1]["session_id"]
    agent = next((s for s in data["live_sessions"] if s["id"] == target), None)
    data["logs"].append({
        "id": data["max_log_id"] + 1, "session_id": target,
        "ts": "2026-08-04T06:43:09+00:00", "type": "system", "content": RECORD,
    })
    data["max_log_id"] += 1

    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"},
            viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        await page.route("**/static/js/app.js*",
                         lambda r: r.fulfill(status=200, content_type="text/javascript",
                                             body=APP_JS.read_text()))
        await page.route("**/api/logs/sync*",
                         lambda r: r.fulfill(status=200, content_type="application/json",
                                             body=json.dumps(data, ensure_ascii=False)))
        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _showChatFor === 'function'")
        await page.wait_for_timeout(4000)
        if agent:
            await page.evaluate("(a) => selectAgent(a.name)", agent)
        await page.wait_for_timeout(2500)
        found = await page.evaluate(
            "() => [...document.querySelectorAll('#chat *')]"
            ".filter(e => e.textContent.includes('[доставка] автоотчёт')).length")
        print(f"  строка найдена в чате: {found > 0} (узлов с ней: {found})")
        await page.locator("#chat").screenshot(path=str(OUT))
        print(f"  скриншот: {OUT}")
        await br.close()
    return 0 if found else 1


sys.exit(asyncio.run(main()))
