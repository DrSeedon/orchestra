"""CPU-profile the dashboard's IDLE main thread and attribute the blocking to functions."""
import asyncio, collections, sys, time
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8888/"
COOKIE = open("/tmp/perf_cookie").read().strip()
IDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 30


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 1600, "height": 900})
        await ctx.add_cookies([{"name": "session", "value": COOKIE,
                                "domain": "127.0.0.1", "path": "/"}])
        page = await ctx.new_page()
        await page.goto(URL, wait_until="load", timeout=60000)
        await page.wait_for_timeout(5000)  # let startup settle

        cdp = await ctx.new_cdp_session(page)
        await cdp.send("Profiler.enable")
        await cdp.send("Profiler.setSamplingInterval", {"interval": 200})
        await cdp.send("Profiler.start")
        t = time.perf_counter()
        await page.wait_for_timeout(IDLE * 1000)
        el = time.perf_counter() - t
        prof = (await cdp.send("Profiler.stop"))["profile"]

        nodes = {n["id"]: n for n in prof["nodes"]}
        self_ticks = collections.Counter()
        for nid in prof["samples"]:
            self_ticks[nid] += 1
        total = len(prof["samples"])
        dur_us = prof["endTime"] - prof["startTime"]
        per_sample = dur_us / 1000 / max(total, 1)

        print(f"=== IDLE CPU PROFILE: {el:.0f}s wall, {total} samples "
              f"({per_sample:.2f}ms/sample) ===")
        idle_n = sum(v for k, v in self_ticks.items()
                     if nodes[k]["callFrame"]["functionName"] in ("(idle)", "(program)", "(garbage collector)"))
        print(f"  main thread busy: {(1 - idle_n/total)*100:.1f}%  "
              f"(~{(1-idle_n/total)*el*1000:.0f}ms of {el*1000:.0f}ms)")
        print("  top self-time frames:")
        for nid, c in self_ticks.most_common(22):
            cf = nodes[nid]["callFrame"]
            fn = cf["functionName"] or "(anonymous)"
            if fn in ("(idle)", "(program)"):
                continue
            url = cf["url"].split("/")[-1]
            line = cf.get("lineNumber", -1) + 1
            print(f"    {c*per_sample:8.0f}ms  {c*per_sample/el/10:5.1f}%  {fn:34s} {url}:{line}")

        await browser.close()


asyncio.run(main())
