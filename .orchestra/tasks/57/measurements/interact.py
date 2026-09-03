"""#57 — цена ПОВСЕДНЕВНЫХ действий, а не первой загрузки.

Жалобы юзера дословно: «переключаю воркера и долго тупит», «файлы не показывает, иногда
вечный лоадинг», «при переключении проектов лагают, долго грузятся». Ни одна не про
загрузку страницы — а мерили мы её. Здесь меряется клик.

На каждое действие снимается:
  first  — от клика до ПЕРВОГО изменения DOM (когда «что-то произошло»),
  quiet  — от клика до тишины 400 мс подряд (когда «всё встало»),
  cpu    — занятость главного потока за это время (CDP Profiler),
  net    — запросы, ушедшие после клика: количество, байты провода и декодированные.
Байты важнее миллисекунд: на VPS RTT≈0, и вся цена канала юзера скрыта. Декодированный
объём переносится на его канал делением на реальную скорость.

Запуск: .venv/bin/python docs/tasks/57/measurements/interact.py [repeats]
"""
import asyncio, collections, json, pathlib, statistics, sys

from playwright.async_api import async_playwright

import cpu_profile as CP

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
OUT = pathlib.Path(__file__).parent / "interact.json"

WATCH = """() => {
  window.__w = {t0: performance.now(), first: null, last: null, muts: 0, nodes: 0};
  window.__obs = new MutationObserver((recs) => {
    const now = performance.now();
    if (window.__w.first === null) window.__w.first = now;
    window.__w.last = now;
    window.__w.muts += recs.length;
    for (const r of recs) window.__w.nodes += r.addedNodes.length;
  });
  window.__obs.observe(document.body, {childList: true, subtree: true, characterData: true});
  window.__resBase = performance.getEntriesByType('resource').length;
}"""

COLLECT = """() => {
  window.__obs.disconnect();
  const w = window.__w;
  const res = performance.getEntriesByType('resource').slice(window.__resBase).map(r => ({
    name: r.name.split('/').slice(3).join('/').split('?')[0],
    start: +r.startTime.toFixed(1), dur: +r.duration.toFixed(1),
    wire: r.transferSize, decoded: r.decodedBodySize,
  }));
  return {
    first: w.first === null ? null : +(w.first - w.t0).toFixed(1),
    quiet: w.last === null ? null : +(w.last - w.t0).toFixed(1),
    muts: w.muts, nodes: w.nodes, res,
    chatNodes: document.querySelectorAll('#chat > *').length,
  };
}"""


async def act(page, cdp, name, do, settle=4.0):
    await page.evaluate(WATCH)
    await cdp.send("Profiler.start")
    try:
        await do()
    except Exception as e:
        await cdp.send("Profiler.stop")
        return {"action": name, "error": repr(e)}
    await asyncio.sleep(settle)
    prof = (await cdp.send("Profiler.stop"))["profile"]
    d = await page.evaluate(COLLECT)
    rows, total, _ = CP.flatten(prof)
    busy = sum(r["self_ms"] for r in rows if r["fn"] != "(idle)")
    top = [(r["fn"], r["url"].split("/")[-1].split("?")[0], r["self_ms"])
           for r in rows if r["fn"] != "(idle)"][:8]
    d.update(action=name, cpu_busy_ms=round(busy, 1), top=top,
             net_n=len(d["res"]), net_wire=sum(r["wire"] for r in d["res"]),
             net_decoded=sum(r["decoded"] for r in d["res"]))
    return d


async def scenario(ctx, page, cdp):
    out = []

    agents = await page.eval_on_selector_all(
        ".agent-item", "els => els.map(e => e.textContent.trim().slice(0, 40))")
    tabs = await page.eval_on_selector_all(
        "#orch-tabs > *", "els => els.map(e => e.textContent.trim().slice(0, 30))")
    print(f"   агентов в списке: {len(agents)}, вкладок оркестраторов: {len(tabs)}")

    if len(agents) >= 2:
        for idx in (1, 0, 2 if len(agents) > 2 else 0):
            out.append(await act(page, cdp, f"переключение агента → #{idx}",
                                 lambda i=idx: page.locator(".agent-item").nth(i).click()))
    out.append(await act(page, cdp, "вкладка FILES",
                         lambda: page.click('[data-left-tab="files"]')))
    rows_n = await page.eval_on_selector_all("#file-tree > *", "e => e.length")
    if rows_n:
        out.append(await act(page, cdp, "раскрыть первую папку",
                             lambda: page.locator("#file-tree > *").first.click()))
    out.append(await act(page, cdp, "вкладка TASKS",
                         lambda: page.click('[data-left-tab="tasks"]')))
    if len(tabs) >= 2:
        out.append(await act(page, cdp, "переключение проекта (вкладка оркестратора)",
                             lambda: page.locator("#orch-tabs > *").nth(1).click(), settle=6.0))
        out.append(await act(page, cdp, "возврат на первый проект",
                             lambda: page.locator("#orch-tabs > *").nth(0).click(), settle=6.0))
    return out


async def main():
    runs = []
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/perf57-interact", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(CP.BASE + "/login")
        await p.fill('input[name="username"]', CP.ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', CP.ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()

        for r in range(REPEATS):
            page = await ctx.new_page()
            cdp = await ctx.new_cdp_session(page)
            await cdp.send("Profiler.enable")
            await cdp.send("Profiler.setSamplingInterval", {"interval": 100})
            await page.goto(CP.BASE + "/", wait_until="load")
            await asyncio.sleep(8)          # дать странице устояться
            print(f"  прогон {r + 1}, loadavg={open('/proc/loadavg').read().split()[0]}")
            runs.append(await scenario(ctx, page, cdp))
            await page.close()
        await ctx.close()
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1))

    agg = collections.defaultdict(list)
    for run in runs:
        for d in run:
            agg[d["action"]].append(d)
    print(f"\n{'действие':44s} {'первый DOM':>11} {'тишина':>9} {'CPU':>8} "
          f"{'запросов':>9} {'КБ (decoded)':>13}")
    for name, ds in agg.items():
        ok = [d for d in ds if "error" not in d]
        if not ok:
            print(f"{name:44s}  ОШИБКА: {ds[0].get('error')}")
            continue
        m = lambda k: statistics.median([d[k] for d in ok if d.get(k) is not None]) \
            if any(d.get(k) is not None for d in ok) else float("nan")
        print(f"{name:44s} {m('first'):9.0f} мс {m('quiet'):7.0f} мс {m('cpu_busy_ms'):6.0f} мс "
              f"{m('net_n'):9.0f} {m('net_decoded') / 1024:13.0f}")
    print("\nсамое дорогое в главном потоке по действиям:")
    for name, ds in agg.items():
        ok = [d for d in ds if "error" not in d]
        if not ok:
            continue
        tot = collections.Counter()
        for d in ok:
            for fn, url, ms in d["top"]:
                tot[f"{fn} [{url}]"] += ms / len(ok)
        print(f"  {name}:")
        for k, v in tot.most_common(4):
            print(f"     {v:7.1f} мс  {k}")
    print("\nсамые тяжёлые ответы (decoded КБ) по действиям:")
    for name, ds in agg.items():
        ok = [d for d in ds if "error" not in d]
        big = collections.Counter()
        for d in ok:
            for r in d["res"]:
                big[r["name"]] = max(big[r["name"]], r["decoded"] / 1024)
        if big:
            print(f"  {name}: " + ", ".join(f"{k} {v:.0f}КБ" for k, v in big.most_common(4)))


asyncio.run(main())
