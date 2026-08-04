"""#8 — сколько запросов и в каком порядке стоит одно переключение агента.

Без аргументов меряет то, что отдаёт живой сервер. С путём к app.js — подменяет файл
через page.route (живой :8888 отдаёт статику из основного чекаута, не из worktree),
что и позволяет гонять «до» и «после» на одной и той же странице.
"""
import asyncio, json, pathlib, subprocess, sys
from playwright.async_api import async_playwright

SYNC_BODY = pathlib.Path("/tmp/m8_sync_body.json").read_text() \
    if pathlib.Path("/tmp/m8_sync_body.json").exists() else "{}"

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        pg = await ctx.new_page()
        override = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if override:
            await pg.route("**/static/js/app.js*",
                           lambda r: r.fulfill(status=200, content_type="text/javascript",
                                               body=override.read_text()))
            await pg.route("**/api/logs/sync*", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=SYNC_BODY))
        reqs = []
        pg.on("request", lambda r: reqs.append(r.url.split(":8888")[-1]))
        await pg.goto("http://127.0.0.1:8888", wait_until="load")
        await pg.wait_for_function("typeof selectAgent === 'function'")
        await pg.wait_for_timeout(6000)
        names = await pg.evaluate("[...document.querySelectorAll('.agent-item .text-xs.font-medium')].map(e=>e.textContent)")
        print("агенты:", names[:6])
        for target in names[:3]:
            reqs.clear()
            t = await pg.evaluate(
                "async (n) => { const t0 = performance.now(); await selectAgent(n); return performance.now() - t0; }",
                target)
            await pg.wait_for_timeout(2500)
            interesting = [u for u in reqs if "/api/" in u]
            print(f"\n--- переключение на {target}: selectAgent() вернулся за {t:.0f} мс, {len(interesting)} запросов")
            for u in interesting:
                print("   ", u[:110])
        await br.close()


asyncio.run(main())
