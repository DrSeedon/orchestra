"""#15 T1 — восстановление после недоступности сервера без перезагрузки страницы.

Недоступность имитируется перехватом запросов (502), сервис orchestra не трогается.
app.js подменяется на версию из ветки: живой :8888 отдаёт статику из основного чекаута.

Запуск: uv run python docs/tasks/15/verify-recovery.py
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
    subprocess.run(["sqlite3", "/home/kesha/orchestra/data/orchestra.db",
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
    down = {"on": False, "recoveries": 0}

    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text))
        await page.route("**/static/js/app.js*",
                         lambda r: r.fulfill(status=200, content_type="text/javascript",
                                             body=APP_JS.read_text()))

        async def api_route(route):
            if down["on"]:
                return await route.fulfill(status=502, content_type="text/html",
                                           body="<html>502 Bad Gateway</html>")
            if "/api/logs/sync" in route.request.url:
                after = int(dict(x.split("=") for x in route.request.url.split("?")[1].split("&"))
                            .get("after_id", 0))
                return await route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(get_logs_sync(after_id=after, tail=100), ensure_ascii=False))
            await route.continue_()
        await page.route("**/api/**", api_route)

        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _recoverAfterOutage === 'function'")
        await page.wait_for_timeout(6000)

        base = await page.evaluate("""() => ({
          navs: performance.getEntriesByType('navigation').length,
          ids: [...document.querySelectorAll('#chat [data-chat-log-id]')].map(n => n.dataset.chatLogId),
          agent: selectedAgent})""")
        check("до опыта чат наполнен", len(base["ids"]) > 0, f'{len(base["ids"])} узлов')

        # Оптимистичный пузырь, который сервер не подтвердил
        await page.evaluate("""() => {
          localMessages.add('черновик который сервер не увидел');
          pendingUserMsgs.push('черновик который сервер не увидел');
        }""")

        # --- сервер падает ---
        down["on"] = True
        await page.wait_for_function("!!_rebootOverlay", timeout=20000)
        check("оверлей ребута показан при недоступности", True)

        # --- сервер вернулся ---
        down["on"] = False
        await page.wait_for_function("!_rebootOverlay && !_recovering", timeout=30000)
        await page.wait_for_timeout(2500)

        after = await page.evaluate("""() => ({
          navs: performance.getEntriesByType('navigation').length,
          ids: [...document.querySelectorAll('#chat [data-chat-log-id]')].map(n => n.dataset.chatLogId),
          overlay: !!_rebootOverlay,
          optimistic: localMessages.size + pendingUserMsgs.length,
          stream: !!eventSource,
          leftover: document.body.textContent.includes('черновик который сервер не увидел')})""")

        check("страница НЕ перезагрузилась",
              after["navs"] == base["navs"] and after["navs"] == 1,
              f'записей navigation: {base["navs"]} → {after["navs"]}')
        check("оверлей снят", not after["overlay"])
        check("история на месте", len(after["ids"]) > 0, f'{len(after["ids"])} узлов')
        check("неподтверждённое оптимистичное состояние выброшено",
              after["optimistic"] == 0 and not after["leftover"],
              f'осталось {after["optimistic"]} записей')
        check("поток переоткрыт", after["stream"])

        # --- совпадает ли результат с честной перезагрузкой ---
        await page.reload(wait_until="load")
        await page.wait_for_function("typeof _showChatFor === 'function'")
        await page.wait_for_timeout(6000)
        reloaded = await page.evaluate("""() => [...document.querySelectorAll('#chat [data-chat-log-id]')]
            .map(n => n.dataset.chatLogId)""")
        check("состав чата совпал с тем, что даёт честная перезагрузка",
              after["ids"] == reloaded,
              f'после восстановления {len(after["ids"])}, после перезагрузки {len(reloaded)}')

        # --- два быстрых возврата подряд дают одну перерисовку ---
        marks = await page.evaluate("""async () => {
          let calls = 0;
          const real = window._showChatFor;
          window._showChatFor = async (...a) => { calls++; return real(...a); };
          _wasDown = true; _onServerOk();
          _wasDown = true; _onServerOk();      // второй источник в тот же тик
          await new Promise(r => setTimeout(r, 2500));
          window._showChatFor = real;
          return calls;
        }""")
        check("два возврата подряд → одна перерисовка", marks == 1, f"перерисовок: {marks}")

        await br.close()

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} проверок прошли")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
