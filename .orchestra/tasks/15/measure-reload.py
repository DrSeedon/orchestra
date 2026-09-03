"""#15 — во что обходится location.reload() после возврата сервера.

Через nginx (как ходит юзер): холодная загрузка, затем reload в том же контексте —
видно, что браузер перезапрашивает и с какими кодами. Плюс замер, когда на экране
появляется история чата.
"""
import asyncio, json
from playwright.async_api import async_playwright

ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()
BASE = "https://orchestra.seedon.ru"


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await br.new_context(
            ignore_https_errors=True,
            extra_http_headers={"Authorization": f"Bearer {ENV['INTERNAL_TOKEN']}"})
        page = await ctx.new_page()
        recs = []
        page.on("response", lambda r: recs.append(
            (r.status, r.url.split("seedon.ru")[-1].split("?")[0],
             r.headers.get("content-length") or "?", r.headers.get("cache-control") or "-")))

        async def snap(tag):
            recs.clear()
            t0 = asyncio.get_event_loop().time()
            await page.reload(wait_until="load") if tag != "cold" else None
            await page.wait_for_function(
                "document.querySelector('#chat') && document.querySelector('#chat').children.length > 0",
                timeout=30000)
            dt = (asyncio.get_event_loop().time() - t0) * 1000
            perf = await page.evaluate("""() => {
              const nav = performance.getEntriesByType('navigation')[0];
              const res = performance.getEntriesByType('resource');
              const st = res.filter(r => /\\.(js|css)(\\?|$)/.test(r.name));
              return {
                ttfb: Math.round(nav.responseStart - nav.requestStart),
                domReady: Math.round(nav.domContentLoadedEventEnd),
                load: Math.round(nav.loadEventEnd),
                staticCount: st.length,
                staticTransfer: st.reduce((a, r) => a + r.transferSize, 0),
                staticDecoded: st.reduce((a, r) => a + r.decodedBodySize, 0),
                fromCache: st.filter(r => r.transferSize === 0).length,
                apiCount: res.filter(r => r.name.includes('/api/')).length,
              };
            }""")
            codes = {}
            for st, u, cl, cc in recs:
                codes[st] = codes.get(st, 0) + 1
            print(f"\n=== {tag}: чат на экране за {dt:.0f} мс ===")
            print(f"  TTFB {perf['ttfb']} мс · DOMContentLoaded {perf['domReady']} мс · load {perf['load']} мс")
            print(f"  статики {perf['staticCount']} файлов, на проводе {perf['staticTransfer']/1024:.0f} КБ "
                  f"(распаковано {perf['staticDecoded']/1024:.0f} КБ), из кеша без сети {perf['fromCache']}")
            print(f"  ответов по кодам: {codes} · запросов к /api/: {perf['apiCount']}")
            for st, u, cl, cc in recs:
                if "/static/" in u or u in ("/",):
                    print(f"    {st} {u:44} cache-control: {cc}")
            return perf

        await page.goto(BASE, wait_until="load")
        await page.wait_for_function("typeof _storeSync === 'function'")
        await page.wait_for_timeout(6000)          # дать зеркалу #8 синхронизироваться
        await snap("cold")
        for i in (1, 2):
            await snap(f"reload #{i}")

        # Троттлинг фонового таймера: сколько живёт heartbeat в скрытой вкладке
        other = await ctx.new_page()
        await other.goto("about:blank")
        await other.bring_to_front()
        ticks = await page.evaluate("""async () => {
          const t0 = performance.now(); let n = 0;
          const id = setInterval(() => n++, 3000);
          await new Promise(r => setTimeout(r, 15000));
          clearInterval(id);
          return {n, hidden: document.hidden, ms: Math.round(performance.now() - t0)};
        }""")
        print(f"\n=== фоновая вкладка: setInterval(3000) за {ticks['ms']} мс сработал "
              f"{ticks['n']} раз (ожидалось ~5), document.hidden={ticks['hidden']} ===")
        await br.close()


asyncio.run(main())
