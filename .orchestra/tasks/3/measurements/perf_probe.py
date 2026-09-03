"""First-load + idle profile of the Orchestra dashboard, measured from the server itself.

Loopback (RTT ~0.2ms) => network is out of the picture; what remains is
server think-time + client parse/render cost.
"""
import asyncio, json, sys, time
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8888/"
COOKIE = open("/tmp/perf_cookie").read().strip()
IDLE_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 1600, "height": 900})
        await ctx.add_cookies([{"name": "session", "value": COOKIE,
                                "domain": "127.0.0.1", "path": "/"}])
        page = await ctx.new_page()

        reqs = []
        page.on("requestfinished", lambda r: reqs.append(r))

        await page.add_init_script("""
            window.__longtasks = [];
            new PerformanceObserver(l => {
                for (const e of l.getEntries()) window.__longtasks.push([e.startTime, e.duration]);
            }).observe({entryTypes: ['longtask']});
        """)

        t0 = time.perf_counter()
        await page.goto(URL, wait_until="load", timeout=60000)
        load_wall = (time.perf_counter() - t0) * 1000

        nav = await page.evaluate("""() => {
            const n = performance.getEntriesByType('navigation')[0];
            const paints = {};
            for (const p of performance.getEntriesByType('paint')) paints[p.name] = p.startTime;
            return {ttfb: n.responseStart, domInteractive: n.domInteractive,
                    dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, paints};
        }""")

        res = await page.evaluate("""() => performance.getEntriesByType('resource').map(r => ({
            name: r.name, dur: r.duration, size: r.transferSize, dec: r.decodedBodySize,
            start: r.startTime, type: r.initiatorType}))""")

        print(f"=== FIRST LOAD (loopback, cold cache) wall={load_wall:.0f}ms ===")
        print(f"  TTFB={nav['ttfb']:.0f}ms  domInteractive={nav['domInteractive']:.0f}ms  "
              f"DCL={nav['dcl']:.0f}ms  load={nav['load']:.0f}ms")
        print(f"  paints={ {k: round(v) for k, v in nav['paints'].items()} }")
        print(f"  resources: n={len(res)}  transfer={sum(r['size'] for r in res)/1024:.0f}KB  "
              f"decoded={sum(r['dec'] for r in res)/1024:.0f}KB")
        print("  slowest resources:")
        for r in sorted(res, key=lambda r: -r["dur"])[:10]:
            print(f"    {r['dur']:7.0f}ms  {r['size']/1024:7.1f}KB tx  {r['name'][-70:]}")

        # let the app settle, then measure long tasks accumulated during startup
        await page.wait_for_timeout(3000)
        lts = await page.evaluate("() => window.__longtasks || []")
        print(f"  long tasks (>50ms, main thread blocked): n={len(lts)} "
              f"total={sum(d for _, d in lts):.0f}ms")
        for s, d in sorted(lts, key=lambda x: -x[1])[:8]:
            print(f"    at {s:7.0f}ms  blocked {d:6.0f}ms")

        # ---- IDLE PHASE ----
        print(f"\n=== IDLE {IDLE_SECONDS}s (dashboard open, zero user input) ===")
        reqs.clear()
        await page.evaluate("() => { window.__longtasks = []; }")
        base = await page.evaluate("() => performance.getEntriesByType('resource').length")
        t = time.perf_counter()
        await page.wait_for_timeout(IDLE_SECONDS * 1000)
        el = time.perf_counter() - t
        idle = await page.evaluate(f"""() => performance.getEntriesByType('resource')
            .slice({base}).map(r => ({{name: r.name, size: r.transferSize, dur: r.duration}}))""")
        by = {}
        for r in idle:
            key = r["name"].split("?")[0].replace("http://127.0.0.1:8888", "")
            e = by.setdefault(key, [0, 0, 0.0])
            e[0] += 1
            e[1] += r["size"]
            e[2] += r["dur"]
        print(f"  requests={len(idle)} ({len(idle)/el*60:.0f}/min)  "
              f"transfer={sum(r['size'] for r in idle)/1024:.1f}KB "
              f"({sum(r['size'] for r in idle)/1024/el*60:.1f}KB/min)")
        for k, (n, sz, dur) in sorted(by.items(), key=lambda x: -x[1][0]):
            print(f"    {n:4d}x  {sz/1024:8.1f}KB  avg {dur/n:6.1f}ms  {k}")
        lts2 = await page.evaluate("() => window.__longtasks || []")
        print(f"  long tasks while idle: n={len(lts2)} total={sum(d for _, d in lts2):.0f}ms")

        await browser.close()


asyncio.run(main())
