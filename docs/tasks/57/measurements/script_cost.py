"""#57 — сколько стоит КАЖДЫЙ скрипт страницы: загрузка, компиляция, верхний уровень.

Каждый <script> отдаётся через route с маркерами в начале и в конце тела:
  t_start — первый оператор файла выполнился (компиляция уже позади),
  t_end   — верхний уровень файла дошёл до конца.
Компиляция = t_start минус момент, когда файл догрузился и до него дошла очередь
(`responseEnd` из resource timing либо конец предыдущего скрипта — берётся поздний).
Репозиторий не меняется: тела читаются с диска и склеиваются в памяти.

Запуск: .venv/bin/python docs/tasks/57/measurements/script_cost.py [repeats]
"""
import asyncio, json, pathlib, statistics, sys

from playwright.async_api import async_playwright

import cpu_profile as CP

ROOT = pathlib.Path("/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-front/app/static")
FILES = ["css/vendor/tailwind.js", "css/vendor/marked.min.js", "css/vendor/purify.min.js",
         "css/vendor/diff_match_patch.js", "css/vendor/chart.umd.min.js",
         "css/vendor/highlight.min.js", "js/utils.js", "js/tool-renderers.js",
         "js/usage.js", "js/analytics.js", "js/app.js"]
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
OUT = pathlib.Path(__file__).parent / "script-cost.json"

PROBE = """() => {
  const res = {};
  for (const r of performance.getEntriesByType('resource'))
    if (r.name.endsWith('.js') || r.name.includes('.js?'))
      res[r.name.split('/').pop().split('?')[0]] = +r.responseEnd.toFixed(1);
  return {marks: window.__sm || {}, res};
}"""


async def run(ctx):
    page = await ctx.new_page()
    bodies = {}
    for rel in FILES:
        name = rel.split("/")[-1]
        src = (ROOT / rel).read_text()
        bodies[name] = (f"window.__sm=window.__sm||{{}};window.__sm['{name}:start']=performance.now();\n"
                        + src +
                        f"\n;window.__sm['{name}:end']=performance.now();")

    async def _serve(route, request):
        name = request.url.split("/")[-1].split("?")[0]
        if name not in bodies:
            return await route.continue_()
        await route.fulfill(status=200, content_type="application/javascript", body=bodies[name])

    await page.route("**/*.js*", _serve)
    await page.goto(CP.BASE + "/", wait_until="load")
    await asyncio.sleep(6)
    data = await page.evaluate(PROBE)
    await page.close()
    return data


async def main():
    runs = []
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/perf57-scriptcost", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(CP.BASE + "/login")
        await p.fill('input[name="username"]', CP.ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', CP.ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()
        await run(ctx)                       # прогрев
        for _ in range(REPEATS):
            runs.append(await run(ctx))
        await ctx.close()
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1))

    print(f"{'файл':28s} {'КБ':>6} {'компиляция':>11} {'верх. уровень':>14}")
    prev_end = None
    for rel in FILES:
        name = rel.split("/")[-1]
        kb = (ROOT / rel).stat().st_size / 1024
        comp, top = [], []
        for r in runs:
            s, e = r["marks"].get(f"{name}:start"), r["marks"].get(f"{name}:end")
            if s is None or e is None:
                continue
            ready = r["res"].get(name)
            base = max(x for x in (ready, r["marks"].get(f"{prev_end}:end")) if x is not None) \
                if (ready is not None or prev_end) else None
            if base is not None:
                comp.append(s - base)
            top.append(e - s)
        c = f"{statistics.median(comp):8.1f} мс" if comp else "     н/д"
        t = f"{statistics.median(top):8.1f} мс" if top else "     н/д"
        print(f"{name:28s} {kb:6.0f} {c:>11} {t:>14}")
        prev_end = name


asyncio.run(main())
