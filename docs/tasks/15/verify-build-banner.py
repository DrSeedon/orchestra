"""#15 T2 — баннер о новой версии фронта, и то, что автоперезагрузки нет.

Живой сервер заголовка X-Orchestra-Build ещё не отдаёт (появится с рестартом), поэтому
подставляем его перехватом — проверяется КЛИЕНТ. app.js берётся из ветки. data-build
живой сервер не отдаёт вовсе (шаблон из main), поэтому вставляем атрибут в HTML на лету:
app.js читает его синхронно при разборе, и init-скрипт до этого момента не успевает.

Запуск: uv run python docs/tasks/15/verify-build-banner.py
"""
import asyncio, pathlib, sys

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
APP_JS = ROOT / "app/static/js/app.js"
BASE = "http://127.0.0.1:8888"
PAGE_BUILD = "build-of-the-page"   # только ASCII: HTTP-заголовки latin-1, кириллица приедет mojibake

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()


RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))
    print(f"  {'OK ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


async def open_dashboard(ctx, console, server_build):
    """Вкладка с подставленной версией страницы и (опционально) версией сервера."""
    page = await ctx.new_page()
    page.on("console", lambda m: console.append(m.text))
    await page.route("**/static/js/app.js*",
                     lambda r: r.fulfill(status=200, content_type="text/javascript",
                                         body=APP_JS.read_text()))
    # data-build правим прямо в HTML: app.js читает его синхронно при разборе, и любой
    # init-скрипт (MutationObserver и прочее) до этого момента не успевает — первый заход
    # так и провалился, _pageBuild приезжал пустым.
    async def doc(route):
        resp = await route.fetch()
        body = await resp.text()
        # Живой сервер рендерит шаблон из main, где data-build ещё нет вовсе, —
        # поэтому атрибут ВСТАВЛЯЕМ в <body>, а не заменяем существующий.
        assert "<body " in body, "шаблон изменился, вставлять некуда"
        await route.fulfill(response=resp,
                            body=body.replace("<body ", f'<body data-build="{PAGE_BUILD}" ', 1))
    await page.route(f"{BASE}/", doc)
    if server_build is not None:
        async def models(route):
            resp = await route.fetch()
            await route.fulfill(response=resp,
                                headers={**resp.headers, "X-Orchestra-Build": server_build})
        await page.route("**/api/models", models)
    await page.goto(BASE, wait_until="load")
    await page.wait_for_function("typeof _heartbeatProbe === 'function'")
    await page.wait_for_timeout(7000)      # два-три тика heartbeat
    return page, await page.evaluate("""() => ({
      banners: document.querySelectorAll('#build-banner').length,
      navs: performance.getEntriesByType('navigation').length,
      pageBuild: _pageBuild,
      text: document.querySelector('#build-banner')?.textContent || ''})""")


async def main():
    console = []
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})

        # --- 1. версии расходятся ---
        page, r = await open_dashboard(ctx, console, "build-of-the-server")
        check("страница знает свою версию", r["pageBuild"] == PAGE_BUILD, r["pageBuild"])
        check("при расхождении версий показан баннер", r["banners"] == 1,
              f'баннеров {r["banners"]}: {r["text"][:60]}')
        check("АВТОПЕРЕЗАГРУЗКИ НЕТ", r["navs"] == 1, f'записей navigation: {r["navs"]}')
        check("причина названа в консоли", any("[build]" in m for m in console),
              [m for m in console if "[build]" in m][:1])
        await page.close()

        # --- 2. версии совпадают ---
        page, r = await open_dashboard(ctx, console, PAGE_BUILD)
        check("совпадающие версии баннер не показывают", r["banners"] == 0,
              f'баннеров {r["banners"]}')
        await page.close()

        # --- 3. старый сервер, заголовка нет вовсе ---
        page, r = await open_dashboard(ctx, console, None)
        check("сервер без заголовка → ни баннера, ни перезагрузки",
              r["banners"] == 0 and r["navs"] == 1, str(r))
        await page.close()

        await br.close()

    bad = [x for x in RESULTS if not x[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} проверок прошли")
    return 1 if bad else 0


sys.exit(asyncio.run(main()))
