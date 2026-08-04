"""#8 — доказательство дефекта приёмки: какой шаблон page.route ловит версионный URL.

После #9 страница грузит /static/js/app.js?v=<build_id>. Проверяем ОБА шаблона на живой
странице: стаб пишет маркер в window, маркер есть → перехват применился.

Запуск: uv run python docs/tasks/8/probe-route-glob.py
"""
import asyncio, pathlib, sys

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8888"
ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

PATTERNS = ["**/static/js/app.js", "**/static/js/app.js*"]


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        urls = []
        page.on("request", lambda r: urls.append(r.url))
        await page.goto(BASE, wait_until="load")
        real = [u for u in urls if "/static/js/app.js" in u]
        print(f"  фактический URL: {real[0].split(':8888')[-1] if real else 'НЕ ЗАПРОШЕН'}")
        await page.close()

        for pat in PATTERNS:
            pg = await ctx.new_page()
            hit = []

            async def stub(route):
                hit.append(route.request.url)
                await route.fulfill(status=200, content_type="text/javascript",
                                    body="window.__STUBBED__ = 'yes';")

            await pg.route(pat, stub)
            await pg.goto(BASE, wait_until="load")
            await pg.wait_for_timeout(1500)
            marker = await pg.evaluate("() => window.__STUBBED__ || 'нет'")
            print(f"  {pat:28} перехвачено запросов {len(hit)}, маркер в странице: {marker}")
            await pg.close()
        await br.close()
    return 0


sys.exit(asyncio.run(main()))
