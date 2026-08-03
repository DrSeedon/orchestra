"""#8 T5 — обрезанная строка в зеркале никогда не доезжает до чата.

Проверять эту ветку надо НАМЕРЕННО: при боевом cap=16 КБ и tail=20 ни одно сообщение
в живой БД не обрезается (блобы со скриншотами лежат глубже последних двадцати), и тест
был бы зелёным просто потому, что код не исполнялся. Поэтому здесь тянем окно до 100
строк и берём агента, у которого в журнале реально лежит base64-скриншот на 636 КБ.

Проверяем: если в зеркале для агента есть хоть одна обрезанная строка, история берётся
с сервера целиком, и картинка рисуется настоящей картинкой, а не обрубком.

Запуск: uv run python docs/tasks/8/verify-truncation.py
"""
import asyncio, json, pathlib, subprocess, sqlite3, sys

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

CAP, TAIL = 4096, 100
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


def pick_victim():
    """Агент, у которого в последних TAIL строках лежит самое большое сообщение."""
    c = sqlite3.connect(f"file:{DB_COPY}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute("""
        WITH r AS (SELECT id, session_id, LENGTH(content) n,
                          ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY id DESC) rn
                   FROM logs)
        SELECT r.id, r.session_id, r.n, s.name, s.scope
        FROM r JOIN sessions s ON s.id = r.session_id
        WHERE r.rn <= ? ORDER BY r.n DESC LIMIT 1""", (TAIL,)).fetchone()
    return dict(rows) if rows else None


async def main():
    victim = pick_victim()
    if not victim:
        print("в БД нет подходящей строки — проверять нечего")
        return 1
    print(f"  подопытный: {victim['name']} ({victim['scope']}), строка {victim['id']}, "
          f"{victim['n'] / 1024:.0f} КБ при cap={CAP}")

    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(m.text))
        await page.route("**/static/js/app.js",
                         lambda r: r.fulfill(status=200, content_type="text/javascript",
                                             body=APP_JS.read_text()))

        async def sync(route):
            after = int(dict(x.split("=") for x in route.request.url.split("?")[1].split("&"))
                        .get("after_id", 0))
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps(get_logs_sync(after_id=after, tail=TAIL, cap=CAP),
                                                ensure_ascii=False))
        await page.route("**/api/logs/sync*", sync)

        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _showChatFor === 'function'")
        await page.wait_for_timeout(5000)

        reqs = []
        page.on("request", lambda r: reqs.append(r.url.split(":8888")[-1]))
        shown = await page.evaluate("""async ({name, scope}) => {
          currentScope = scope; selectedAgent = name;
          await _showChatFor(name, scope);
          return document.querySelector('#chat').children.length;
        }""", {"name": victim["name"], "scope": victim["scope"]})
        await page.wait_for_timeout(1500)
        check("история подопытного агента нарисована", shown > 0, f"{shown} узлов")

        mirror = get_logs_sync(after_id=0, tail=TAIL, cap=CAP)["logs"]
        cut = [r for r in mirror if r["session_id"] == victim["session_id"] and "trunc" in r]
        check("в зеркале этого агента обрезанные строки ЕСТЬ (ветка исполнилась)",
              len(cut) > 0, f"обрезано {len(cut)} строк, типы: {sorted({r['type'] for r in cut})}")
        check("из-за них история взята с сервера, а не из зеркала",
              len([u for u in reqs if "/logs?" in u]) == 1,
              str([u[-44:] for u in reqs if "/logs?" in u]))

        node = await page.evaluate("""(id) => {
          const n = document.querySelector(`#chat [data-chat-log-id="${id}"]`);
          const imgs = [...document.querySelectorAll('#chat img')];
          return {imgs: imgs.length, src: imgs.map(i => i.src.slice(0, 22)),
                  broken: imgs.filter(i => i.complete && i.naturalWidth === 0).length};
        }""", victim["id"])
        check("картинка из 636-килобайтного сообщения отрисована",
              node["imgs"] > 0 and any(s.startswith("data:image") for s in node["src"]),
              f'изображений {node["imgs"]}, префиксы {node["src"][:2]}')
        check("битых изображений нет", node["broken"] == 0,
              f'битых {node["broken"]} из {node["imgs"]}')

        # А теперь тот же агент, но с боевым cap — обрезки нет, история из зеркала
        boevoy = get_logs_sync(after_id=0, tail=20, cap=16384)["logs"]
        check("при боевых tail=20 и cap=16 КБ не обрезается ни одна строка во ВСЕЙ базе",
              not any("trunc" in r for r in boevoy),
              f'{sum(1 for r in boevoy if "trunc" in r)} обрезанных из {len(boevoy)}')

        await br.close()

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} проверок прошли")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
