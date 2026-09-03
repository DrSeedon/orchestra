"""#57 — парные плечи: базовая страница ↔ заглушка, чередование в ОДНОМ окне.

Машина нагружена (loadavg 4-6), поэтому абсолюты между отдельными сессиями скачут
сильнее эффекта — это уже ловили в #32. Читаются только ПАРНЫЕ разницы: пары идут
подряд, base → stub → base → stub, кеш прогрет одинаково.

Запуск: .venv/bin/python docs/tasks/57/measurements/pair_run.py <stub> <pairs> [wait_s]
"""
import asyncio, json, os, pathlib, statistics, sys

from playwright.async_api import async_playwright

import cpu_profile as CP

STUB = sys.argv[1]
PAIRS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
WAIT = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
OUT = pathlib.Path(__file__).parent / f"pairs-{STUB}.json"


async def one(ctx, stub, wait):
    page = await ctx.new_page()
    hits = []
    if stub:
        pattern, body = CP._stub_body(stub)

        async def _serve(route):
            hits.append(1)
            await route.fulfill(status=200, content_type="application/javascript", body=body)

        await page.route(pattern, _serve)
    await page.add_init_script(CP.INIT)
    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Profiler.enable")
    await cdp.send("Profiler.setSamplingInterval", {"interval": 100})
    await cdp.send("Profiler.start")
    await page.goto(CP.BASE + "/", wait_until="load")
    await asyncio.sleep(wait)
    now = await page.evaluate("performance.now()")
    prof = (await cdp.send("Profiler.stop"))["profile"]
    data = await page.evaluate(CP.PROBE)
    if stub and not hits:
        raise SystemExit(f"заглушка {stub} не сработала")
    rows, total_ms, _ = CP.flatten(prof)
    prof["__now_at_stop"] = now
    data.update(stub=stub or "base", now_at_stop=now, cpu_total_ms=total_ms,
                loadavg=open("/proc/loadavg").read().split()[:3],
                by_file=dict(CP.by_file(rows).most_common()))
    await page.close()
    return data, prof


async def main():
    res = []
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            f"/tmp/perf57-pairs-{STUB}", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(CP.BASE + "/login")
        await p.fill('input[name="username"]', CP.ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', CP.ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()
        await one(ctx, None, 4)  # прогревочный заход, в статистику не идёт
        for i in range(PAIRS):
            for kind in ("base", STUB):
                base_stub = os.environ.get("PAIR_BASE_STUB") or None
                d, prof = await one(ctx, base_stub if kind == "base" else STUB, WAIT)
                d["pair"] = i
                res.append(d)
                (OUT.parent / f"raw-pair{i}-{kind}-{STUB}.cpuprofile").write_text(json.dumps(prof))
                print(f"  pair{i} {kind:16s} load={d['loadavg'][0]} marks={d['marks']} "
                      f"lt={sum(x['dur'] for x in d['longtasks']):.0f}ms")
        await ctx.close()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    def val(d, k):
        if k == "lt":
            return sum(x["dur"] for x in d["longtasks"])
        if k == "dcl":
            return d["nav"]["domContentLoaded"]
        if k.startswith("f:"):
            return d["by_file"].get(k[2:], 0.0)
        return d["marks"].get(k)

    print(f"\nПарные разницы ({STUB} − base), медиана по {PAIRS} парам:")
    for k in ("dcl", "chatFirst", "chat20", "lt", "f:tailwind.js", "f:app.js", "f:(program)"):
        diffs = []
        for i in range(PAIRS):
            a = next(d for d in res if d["pair"] == i and d["stub"] == "base")
            b = next(d for d in res if d["pair"] == i and d["stub"] == STUB)
            va, vb = val(a, k), val(b, k)
            if va is None or vb is None:
                continue
            diffs.append(vb - va)
        if diffs:
            neg = sum(1 for d in diffs if d < 0)
            print(f"  {k:16s} медиана {statistics.median(diffs):+8.0f} мс   "
                  f"в минус {neg}/{len(diffs)}   [{', '.join(f'{d:+.0f}' for d in diffs)}]")


asyncio.run(main())
