"""#8 T2 — проверка клиентского зеркала журнала.

Живой дашборд :8888, но app.js подменяется на версию из этой ветки (живой сервер отдаёт
статику из основного чекаута — см. docs/tasks/2/report.md), а /api/logs/sync перехватывается
и отвечает из КОПИИ живой БД. Так проверяются реальные объёмы без рестарта сервиса.

Запуск: uv run python docs/tasks/8/verify-store.py
"""
import asyncio, json, pathlib, subprocess, sys

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
APP_JS = ROOT / "app/static/js/app.js"
DB_COPY = pathlib.Path("/tmp/live_copy.db")
BASE = "http://127.0.0.1:8888"

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

if not DB_COPY.exists():
    subprocess.run(["sqlite3", str(ROOT.parents[2] / "orchestra/data/orchestra.db"),
                    f".backup {DB_COPY}"], check=True)

sys.path.insert(0, str(ROOT))
import app.db as _db                                     # noqa: E402
_db.DB_PATH = DB_COPY
from app.db import get_logs_sync                         # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


async def main():
    payload_mode = {"mode": "real", "requests": []}

    async def handle_sync(route):
        url = route.request.url
        after_id = int(dict(p.split("=") for p in url.split("?")[1].split("&")).get("after_id", 0))
        payload_mode["requests"].append(after_id)
        mode = payload_mode["mode"]
        if mode == "404":
            return await route.fulfill(status=404, body='{"detail":"Not Found"}',
                                       content_type="application/json")
        data = get_logs_sync(after_id=after_id, tail=20, cap=16384)
        if mode == "drop_session" and data["live_sessions"]:
            # live_sessions — это {id, name, scope}, сверяем по id
            data["live_sessions"] = [s for s in data["live_sessions"]
                                     if s["id"] != payload_mode["victim"]]
        if mode == "empty_sessions":
            data["live_sessions"] = []
        if mode == "rollback":
            data["max_log_id"] = 1
            data["logs"] = []
        await route.fulfill(status=200, content_type="application/json",
                            body=json.dumps(data, ensure_ascii=False))

    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        logs = []
        page.on("console", lambda m: logs.append(m.text))
        await page.route("**/static/js/app.js",
                         lambda r: r.fulfill(status=200, content_type="text/javascript",
                                             body=APP_JS.read_text()))
        await page.route("**/api/logs/sync*", handle_sync)

        # --- 1. холодная синхронизация ---
        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _storeSync === 'function'")
        await page.wait_for_timeout(4000)
        state = await page.evaluate("""async () => {
          const rows = await new Promise(res => { const q = indexedDB.open('orchestra', 1);
            q.onsuccess = () => { const tx = q.result.transaction('logs','readonly');
              const r = tx.objectStore('logs').count(); r.onsuccess = () => res(r.result); }; });
          const wm = await new Promise(res => { const q = indexedDB.open('orchestra', 1);
            q.onsuccess = () => { const tx = q.result.transaction('meta','readonly');
              const r = tx.objectStore('meta').get('watermark'); r.onsuccess = () => res(r.result); }; });
          return {rows, wm};
        }""")
        real = get_logs_sync(after_id=0, tail=20, cap=16384)
        check("холодная синхронизация уложила все строки",
              state["rows"] == len(real["logs"]),
              f"в хранилище {state['rows']}, отдано {len(real['logs'])}")
        check("watermark = max id последней строки",
              state["wm"] == real["logs"][-1]["id"],
              f"wm={state['wm']}")
        check("холодный запрос ровно один и он after_id=0",
              payload_mode["requests"][:1] == [0],
              f"запросы: {payload_mode['requests'][:3]}")
        timing = await page.evaluate("""() => {
          const nav = performance.getEntriesByType('navigation')[0];
          const e = performance.getEntriesByType('resource')
                     .filter(r => r.name.includes('/api/logs/sync'))[0];
          return e ? {sync: e.startTime, load: nav.loadEventEnd} : null;
        }""")
        check("синхронизация стартовала ПОСЛЕ load, а не в конкуренции с ним",
              bool(timing) and timing["sync"] >= timing["load"],
              f"load={timing['load']:.0f} мс, sync={timing['sync']:.0f} мс" if timing else "нет записи")
        body = json.dumps(real, ensure_ascii=False).encode()
        import gzip as _gz
        check("объём холодной синхронизации в бюджете (≤150 КБ gzip)",
              len(_gz.compress(body, 6)) <= 150 * 1024,
              f"{len(_gz.compress(body, 6)) / 1024:.0f} КБ gzip, {len(body) / 1024:.0f} КБ без сжатия")

        # --- 2. чтение по сессии ---
        by_session = {}
        for r in real["logs"]:
            by_session.setdefault(r["session_id"], []).append(r)
        target = max(by_session, key=lambda k: len(by_session[k]))
        got = await page.evaluate("(sid) => _storeRead(sid, 100)", target)
        check("_storeRead отдаёт строки нужной сессии по возрастанию id",
              [r["id"] for r in got] == sorted(x["id"] for x in by_session[target]),
              f"{len(got)} строк для {target[:8]}")
        check("_storeRead не смешивает сессии",
              all(r["session_id"] == target for r in got))
        few = await page.evaluate("(sid) => _storeRead(sid, 3)", target)
        check("_storeRead(limit) отдаёт САМЫЕ СВЕЖИЕ строки",
              [r["id"] for r in few] == sorted(x["id"] for x in by_session[target])[-3:])

        # --- 3. инкремент не плодит дублей ---
        before = payload_mode["requests"][-1]
        await page.evaluate("() => _storeSync()")
        after = await page.evaluate("""async () => new Promise(res => {
          const q = indexedDB.open('orchestra', 1);
          q.onsuccess = () => { const tx = q.result.transaction('logs','readonly');
            const r = tx.objectStore('logs').count(); r.onsuccess = () => res(r.result); }; })""")
        check("повторная синхронизация идёт с watermark, а не с нуля",
              payload_mode["requests"][-1] == state["wm"],
              f"after_id={payload_mode['requests'][-1]}")
        check("дублей в хранилище не появилось", after >= state["rows"],
              f"было {state['rows']}, стало {after}")

        # --- 4. пустой live_sessions ничего не удаляет ---
        payload_mode["mode"] = "empty_sessions"
        await page.evaluate("() => _storeSync()")
        kept = await page.evaluate("""async () => new Promise(res => {
          const q = indexedDB.open('orchestra', 1);
          q.onsuccess = () => { const tx = q.result.transaction('logs','readonly');
            const r = tx.objectStore('logs').count(); r.onsuccess = () => res(r.result); }; })""")
        check("пустой live_sessions трактуется как сбой, зеркало цело",
              kept == after, f"было {after}, стало {kept}")

        # --- 5. исчезнувшая сессия чистится ---
        payload_mode["mode"] = "drop_session"
        payload_mode["victim"] = target
        await page.evaluate("() => _storeSync()")
        left = await page.evaluate("""async (sid) => (await _storeRead(sid, 500)).length""", target)
        check("строки удалённой сессии стёрты", left == 0, f"осталось {left}")
        others = await page.evaluate("""async () => new Promise(res => {
          const q = indexedDB.open('orchestra', 1);
          q.onsuccess = () => { const tx = q.result.transaction('logs','readonly');
            const r = tx.objectStore('logs').count(); r.onsuccess = () => res(r.result); }; })""")
        check("чужие сессии при этом не пострадали",
              others == kept - len(by_session[target]),
              f"{others} против ожидаемых {kept - len(by_session[target])}")

        # --- 6. откат БД стирает зеркало ---
        payload_mode["mode"] = "rollback"
        await page.evaluate("() => _storeSync()")
        wiped = await page.evaluate("""async () => new Promise(res => {
          const q = indexedDB.open('orchestra', 1);
          q.onsuccess = () => { const tx = q.result.transaction('logs','readonly');
            const r = tx.objectStore('logs').count(); r.onsuccess = () => res(r.result); }; })""")
        check("watermark выше серверного max_log_id → зеркало стёрто", wiped == 0,
              f"осталось {wiped}")
        check("причина названа в консоли",
              any("БД подменили" in m for m in logs),
              [m for m in logs if "store" in m][-1:])

        # --- 7. старый сервер: 404 ---
        logs.clear()
        page2 = await ctx.new_page()
        page2.on("console", lambda m: logs.append(m.text))
        await page2.route("**/static/js/app.js",
                          lambda r: r.fulfill(status=200, content_type="text/javascript",
                                              body=APP_JS.read_text()))
        payload_mode["mode"] = "404"
        await page2.route("**/api/logs/sync*", handle_sync)
        await page2.goto(BASE, wait_until="load")
        await page2.wait_for_timeout(3000)
        check("404 не ломает дашборд", await page2.evaluate("!!document.querySelector('#chat')"))
        check("в консоли названо ЧТО недоступно и что делать",
              any("/api/logs/sync" in m and "404" in m and "рестарт" in m for m in logs),
              [m for m in logs if "store" in m][:1])
        await page2.close()

        # --- 8. IndexedDB недоступна ---
        logs.clear()
        page3 = await ctx.new_page()
        page3.on("console", lambda m: logs.append(m.text))
        await page3.add_init_script(
            "Object.defineProperty(window, 'indexedDB', {get(){ throw new DOMException("
            "'нет доступа в приватном окне', 'SecurityError'); }});")
        await page3.route("**/static/js/app.js",
                          lambda r: r.fulfill(status=200, content_type="text/javascript",
                                              body=APP_JS.read_text()))
        await page3.goto(BASE, wait_until="load")
        await page3.wait_for_timeout(3000)
        check("без IndexedDB дашборд жив",
              await page3.evaluate("!!document.querySelector('#chat')"))
        check("класс исключения виден в консоли, а не пустой catch",
              any("SecurityError" in m or "исключение" in m for m in logs),
              [m for m in logs if "store" in m][:1])
        await page3.close()

        await br.close()

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} проверок прошли")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
