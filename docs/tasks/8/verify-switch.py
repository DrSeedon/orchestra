"""#8 T3/T4 — переключение агента: сколько запросов, откуда история, и что с чужой сессией.

Живой :8888 (СТАРЫЙ сервер, без /api/logs/sync и без события __session) — то есть заодно
это проверка совместимости нового JS со старым маршрутом. app.js подменяется на версию из
ветки, /api/logs/sync отвечает из копии живой БД.

Запуск: uv run python docs/tasks/8/verify-switch.py
"""
import asyncio, json, pathlib, sqlite3, subprocess, sys

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

if not DB_COPY.exists() or not sqlite3.connect(DB_COPY).execute(
        "SELECT 1 FROM sqlite_master WHERE name='logs'").fetchone():
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
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text))
        reqs = []
        page.on("request", lambda r: reqs.append(r.url.split(":8888")[-1]))
        await page.route("**/static/js/app.js*",
                         lambda r: r.fulfill(status=200, content_type="text/javascript",
                                             body=APP_JS.read_text()))

        async def sync(route):
            after = int(dict(x.split("=") for x in route.request.url.split("?")[1].split("&"))
                        .get("after_id", 0))
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps(get_logs_sync(after_id=after, tail=20),
                                                ensure_ascii=False))
        await page.route("**/api/logs/sync*", sync)

        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _showChatFor === 'function'")
        await page.wait_for_timeout(5000)          # даём холодной синхронизации осесть

        await page.wait_for_selector(".agent-item", timeout=15000)
        names = await page.evaluate(
            "[...document.querySelectorAll('.agent-item .text-xs.font-medium')].map(e=>e.textContent)")
        # Без этого пустой список агентов даёт три ВАКУУМНО зелёные проверки (all([]) == True),
        # и прогон выглядит успешным, ничего не проверив.
        if len(names) < 4:
            sys.exit(f"список агентов не отрисовался ({names}) — прогон недействителен")

        # --- 1. переключение при попадании в зеркало ---
        hits = []
        for target in names[:4]:
            reqs.clear()
            t = await page.evaluate("""async (n) => {
              const t0 = performance.now();
              await selectAgent(n);
              return {ms: performance.now() - t0, nodes: document.querySelector('#chat').children.length};
            }""", target)
            await page.wait_for_timeout(700)
            hist = [u for u in reqs if "/logs?" in u or "/stream?" in u]
            hits.append((target, t["ms"], t["nodes"], hist))
        for name, ms, nodes, hist in hits:
            print(f"     {name[:26]:26} {ms:6.0f} мс, узлов {nodes:3}, запросы истории: "
                  f"{[h.split('/')[-1][:38] for h in hist]}")
        check("контент на экране без единого запроса истории",
              all(n > 0 and not [h for h in hist if '/logs?' in h] for _, _, n, hist in hits))
        check("поток открывается ровно один раз на переключение",
              all(len([h for h in hist if '/stream?' in h]) == 1 for *_, hist in hits))
        check("поток просит только хвост, режима after_id=0&limit= нет",
              all("after_id=0&" not in h and not h.endswith("after_id=0")
                  for *_, hist in hits for h in hist if "/stream?" in h),
              [h.split("?")[-1][-40:] for *_, hist in hits for h in hist if "/stream?" in h][:3])
        check("переключение укладывается в 300 мс",
              all(ms < 300 for _, ms, _, _ in hits),
              f"максимум {max(ms for _, ms, _, _ in hits):.0f} мс")

        # --- 2. промах зеркала: одна gzip-загрузка истории ---
        await page.evaluate("""async () => new Promise(res => {
          const q = indexedDB.open('orchestra', 1);
          q.onsuccess = () => { const tx = q.result.transaction('logs','readwrite');
            tx.objectStore('logs').clear(); tx.oncomplete = res; }; })""")
        reqs.clear()
        miss = await page.evaluate("""async (n) => {
          const t0 = performance.now(); await selectAgent(n);
          return {ms: performance.now() - t0, nodes: document.querySelector('#chat').children.length};
        }""", names[1])
        await page.wait_for_timeout(900)
        hist = [u for u in reqs if "/logs?" in u or "/stream?" in u]
        check("промах: ровно одна загрузка истории через /logs",
              len([h for h in hist if "/logs?" in h]) == 1, str([h[-46:] for h in hist]))
        check("промах: контент всё равно нарисован", miss["nodes"] > 0,
              f'{miss["nodes"]} узлов за {miss["ms"]:.0f} мс')
        # Сжатие — работа nginx, а браузер в этом прогоне ходит прямо в :8888 мимо него,
        # поэтому в самой вкладке transferSize == decodedBodySize и мерить там нечего.
        # Смотрим тот же URL так, как его видит юзер, — через nginx.
        url = [u for u in reqs if "/logs?" in u][-1]
        head = subprocess.run(
            ["curl", "-sk", "-D-", "-o", "/dev/null", "-H", "Accept-Encoding: gzip",
             "-H", f"Authorization: Bearer {ENV['INTERNAL_TOKEN']}",
             f"https://orchestra.seedon.ru{url}"], capture_output=True, text=True).stdout
        gz = "content-encoding: gzip" in head.lower()
        size = subprocess.run(
            ["curl", "-sk", "-o", "/dev/null", "-w", "%{size_download}",
             "-H", "Accept-Encoding: gzip", "-H", f"Authorization: Bearer {ENV['INTERNAL_TOKEN']}",
             f"https://orchestra.seedon.ru{url}"], capture_output=True, text=True).stdout
        check("через nginx та же история едет сжатой (D1)", gz,
              f"{size} байт gzip против {enc_plain} без сжатия"
              if (enc_plain := await page.evaluate(
                  "() => performance.getEntriesByType('resource')"
                  ".filter(r => r.name.includes('/logs?')).pop()?.decodedBodySize")) else "")

        # --- 3. «Load more» и позиция чата не сломались ---
        more = await page.evaluate("() => !!document.querySelector('#load-more-btn')")
        cnt = await page.evaluate("() => chatLogs[selectedAgent]?.initialCount")
        check("кнопка Load more показана ровно когда страница заполнена",
              more == (cnt >= 100), f"initialCount={cnt}, кнопка={more}")

        # --- 4. чужая сессия в потоке ---
        console.clear()
        reqs.clear()
        before = await page.evaluate("""() => ({
          nodes: document.querySelector('#chat').children.length,
          sid: _chatSessionId, agent: selectedAgent})""")
        await page.evaluate("""() => {
          eventSource.onmessage({data: JSON.stringify({
            id: 999999999, session_id: 'ЧУЖАЯ-СЕССИЯ', ts: new Date().toISOString(),
            type: 'text', content: 'хвост чужой сессии'})});
        }""")
        await page.wait_for_timeout(1500)
        after = await page.evaluate("""() => ({
          nodes: document.querySelector('#chat').children.length,
          sid: _chatSessionId,
          mixed: [...document.querySelectorAll('#chat *')].some(
                   e => e.textContent === 'хвост чужой сессии')})""")
        check("чужая строка в чат не попала", not after["mixed"])
        # Проверяем ПОВЕДЕНИЕ (чат переоткрыт), а не значение _chatSessionId: подсунутый
        # id ненастоящий, и фоновый renderAgentList раз в 3 с законно возвращает туда
        # правду с сервера. Сверка с подделкой краснела бы через раз от гонки с опросом.
        check("чат перезагружен, а не дополнен: поток переоткрыт",
              len([u for u in reqs if "/stream?" in u]) >= 1,
              f'{before["sid"]} → {after["sid"]}, потоков после подсовывания: '
              f'{len([u for u in reqs if "/stream?" in u])}')
        check("причина названа в консоли",
              any("поток отдаёт сессию" in m for m in console),
              [m for m in console if "chat" in m][:1])

        # --- 5. новый JS против старого сервера (живой :8888 не знает __session) ---
        check("на старом сервере (без __session) чат всё равно наполняется",
              before["nodes"] > 0 and after["nodes"] > 0,
              f'{before["nodes"]} → {after["nodes"]} узлов')

        await br.close()

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} проверок прошли")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
