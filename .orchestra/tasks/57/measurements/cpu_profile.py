"""#57 — из чего складываются длинные задачи главного потока, ПОФУНКЦИОНАЛЬНО.

Тот же вход и те же плечи, что у #32 (`browser_load.py`), но вместо байтов и меток
снимается CPU-профиль главного потока через CDP `Profiler` + категории через
`Performance.getMetrics` (ScriptDuration / RecalcStyleDuration / LayoutDuration).

Замер идёт с VPS: RTT≈0, поэтому ЧИТАЮТСЯ ТОЛЬКО ДОЛИ, абсолютные мс занижены.

Запуск: /home/kesha/orchestra/.venv/bin/python docs/tasks/57/measurements/cpu_profile.py <label> [wait_s]
"""
import asyncio, collections, json, os, pathlib, sys, time

from playwright.async_api import async_playwright

BASE = os.environ.get("PERF57_BASE", "https://orchestra.seedon.ru")
ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip().strip('"')

LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
OUT = pathlib.Path(__file__).parent / f"prof-{LABEL}.json"

INIT = """
window.__lt = []; window.__marks = {};
try { new PerformanceObserver(l => { for (const e of l.getEntries())
        window.__lt.push({start: +e.startTime.toFixed(1), dur: +e.duration.toFixed(1)}); })
      .observe({type: 'longtask', buffered: true}); } catch (e) {}
document.addEventListener('DOMContentLoaded', () => {
  const mark = (key, sel, min) => {
    const obs = new MutationObserver(() => {
      if (document.querySelectorAll(sel).length >= min && !window.__marks[key]) {
        window.__marks[key] = +performance.now().toFixed(1);
      }
    });
    obs.observe(document.body, {childList: true, subtree: true});
  };
  mark('agentsListed', '.agent-item', 1);
  mark('chatFirst', '#chat > *', 1);
  mark('chat20', '#chat > *', 20);
  mark('chat100', '#chat > *', 100);
});
"""

PROBE = """() => {
  const nav = performance.getEntriesByType('navigation')[0];
  return {
    nav: nav ? {domContentLoaded: +nav.domContentLoadedEventEnd.toFixed(1),
                load: +nav.loadEventEnd.toFixed(1)} : null,
    longtasks: window.__lt || [], marks: window.__marks || {},
    chatNodes: document.querySelectorAll('#chat > *').length,
    domNodes: document.getElementsByTagName('*').length,
    styleSheets: document.styleSheets.length,
    cssRules: (() => { let n = 0; for (const s of document.styleSheets) {
        try { n += s.cssRules.length; } catch (e) {} } return n; })(),
  };
}"""


def flatten(profile):
    """Профиль CDP → self-time по узлам. hitCount * (длительность прогона / всего сэмплов)."""
    nodes = {n["id"]: n for n in profile["nodes"]}
    total_hits = sum(n.get("hitCount", 0) for n in profile["nodes"]) or 1
    span_ms = (profile["endTime"] - profile["startTime"]) / 1000.0
    # сэмплер спит, когда поток простаивает → мс на сэмпл считаем по реальным дельтам
    per_hit = sum(profile["timeDeltas"]) / 1000.0 / total_hits
    parent = {}
    for n in profile["nodes"]:
        for c in n.get("children", []):
            parent[c] = n["id"]

    def stack(nid, depth=12):
        out = []
        while nid and depth:
            cf = nodes[nid]["callFrame"]
            out.append(cf.get("functionName") or "(anonymous)")
            nid = parent.get(nid)
            depth -= 1
        return out

    rows = []
    for n in profile["nodes"]:
        h = n.get("hitCount", 0)
        if not h:
            continue
        cf = n["callFrame"]
        rows.append({
            "fn": cf.get("functionName") or "(anonymous)",
            "url": cf.get("url", ""),
            "line": cf.get("lineNumber", -1) + 1,
            "hits": h,
            "self_ms": round(h * per_hit, 1),
            "stack": stack(parent.get(n["id"])),
        })
    rows.sort(key=lambda r: -r["hits"])
    return rows, round(total_hits * per_hit, 1), round(span_ms, 1)


def by_file(rows):
    agg = collections.Counter()
    for r in rows:
        u = r["url"].split("?")[0].rsplit("/", 1)[-1] or "(inline/vm)"
        agg[u] += r["self_ms"]
    return agg


_GEN_CSS = (pathlib.Path(__file__).parent / "tailwind-generated.css")
STUBS = {
    # заглушка вместо Play-CDN Tailwind: страница остаётся без стилей, но вся остальная
    # работа главного потока идёт как обычно → верхняя граница цены tailwind.js
    "tailwind": ("**/css/vendor/tailwind.js*", "window.tailwind={config:{}};"),
    "highlight": ("**/css/vendor/highlight.min.js*", "window.hljs={highlightElement(){},"
                                                     "highlightAll(){},getLanguage(){return null},"
                                                     "highlight(c){return{value:c}}};"),
    # то же место в разборе документа, тот же итоговый CSS — но без компилятора и observer'а.
    # Это симуляция ПРЕДЛАГАЕМОЙ правки, а не «страницы без стилей».
    "tailwind_static": ("**/css/vendor/tailwind.js*", None),
    # приёмка #64: ровно тот CSS, который теперь коммитится, вместо компилятора
    "tailwind_built": ("**/css/vendor/tailwind.js*", None),
    # app.js без принудительной раскладки на каждое сообщение (см. appjs_variant.py)
    "chatscroll": ("**/static/js/app.js*", None),
    # тот же route-перехват, но исходник БЕЗ правок — опорное плечо для пары:
    # перехват вырубает HTTP-кеш, значит оба плеча должны быть перехвачены одинаково
    "appjs_base": ("**/static/js/app.js*", None),
}


def _stub_body(name):
    pattern, body = STUBS[name]
    if name in ("chatscroll", "appjs_base"):
        import appjs_variant
        body = appjs_variant.build()[0] if name == "chatscroll" else appjs_variant.SRC.read_text()
    if name in ("tailwind_static", "tailwind_built"):
        css = (_GEN_CSS if name == "tailwind_static" else
               pathlib.Path(__file__).resolve().parents[4] / "app/static/css/vendor/tailwind.css").read_text()
        body = ("window.tailwind={config:{}};var s=document.createElement('style');"
                f"s.textContent={json.dumps(css)};document.head.appendChild(s);")
    return pattern, body


async def arm(ctx, label, only_cold=False):
    page = await ctx.new_page()
    stub = os.environ.get("PERF57_STUB")
    if stub:
        pattern, body = _stub_body(stub)
        hits = []

        async def _serve(route):
            hits.append(1)
            await route.fulfill(status=200, content_type="application/javascript", body=body)

        await page.route(pattern, _serve)
    await page.add_init_script(INIT)
    cdp = await ctx.new_cdp_session(page)
    await cdp.send("Profiler.enable")
    await cdp.send("Profiler.setSamplingInterval", {"interval": 100})
    await cdp.send("Performance.enable")
    await cdp.send("Profiler.start")
    t0 = time.time()
    await page.goto(BASE + "/", wait_until="load")
    await asyncio.sleep(WAIT)
    metrics = {m["name"]: m["value"] for m in (await cdp.send("Performance.getMetrics"))["metrics"]}
    # якорь для перевода времён профиля (µs, свой ноль) в performance.now() страницы:
    # снимается вплотную к Profiler.stop, расхождение — единицы мс
    now_at_stop = await page.evaluate("performance.now()")
    prof = (await cdp.send("Profiler.stop"))["profile"]
    data = await page.evaluate(PROBE)
    rows, total_ms, span_ms = flatten(prof)
    prof["__now_at_stop"] = now_at_stop
    if stub and not hits:
        raise SystemExit(f"заглушка {stub} не сработала — цифры были бы от обычной страницы")
    data.update(label=label, stub=stub or "", now_at_stop=now_at_stop,
                wallclock_s=round(time.time() - t0, 2),
                loadavg=open("/proc/loadavg").read().split()[:3],
                cpu_total_ms=total_ms, profile_span_ms=span_ms,
                metrics={k: round(v, 4) for k, v in metrics.items()
                         if k in ("ScriptDuration", "RecalcStyleDuration", "LayoutDuration",
                                  "TaskDuration", "LayoutCount", "RecalcStyleCount",
                                  "JSHeapUsedSize", "Nodes")},
                top=rows[:60], by_file=dict(by_file(rows).most_common()))
    (OUT.parent / f"raw-{label}-{LABEL}.cpuprofile").write_text(json.dumps(prof))
    await page.close()
    return data


async def main():
    profile = pathlib.Path(f"/tmp/perf57-profile-{LABEL}")
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(profile), headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(BASE + "/login")
        await p.fill('input[name="username"]', ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()

        arms = [await arm(ctx, "cold")]
        if not os.environ.get("PERF57_ONLY_COLD"):
            arms += [await arm(ctx, "warm1"), await arm(ctx, "warm2")]
        await ctx.close()
    OUT.write_text(json.dumps({a["label"]: a for a in arms}, ensure_ascii=False, indent=1))
    for d in arms:
        lt = d["longtasks"]
        print(f"\n[{d['label']}] load={d['loadavg']} chatNodes={d['chatNodes']} "
              f"domNodes={d['domNodes']} cssRules={d['cssRules']}")
        print(f"  marks: {d['marks']}  dcl={d['nav']['domContentLoaded'] if d['nav'] else '?'}")
        print(f"  longtasks n={len(lt)} total={sum(x['dur'] for x in lt):.0f}ms "
              f"max={max([x['dur'] for x in lt], default=0):.0f}ms")
        print(f"  CDP metrics: {d['metrics']}")
        print(f"  CPU total={d['cpu_total_ms']}ms over span={d['profile_span_ms']}ms")
        print("  по файлам (self ms):")
        for k, v in list(d["by_file"].items())[:10]:
            print(f"   {v:8.1f}  {k}")
        print("  по функциям (self ms):")
        for r in d["top"][:20]:
            src = r["url"].rsplit("/", 1)[-1]
            print(f"   {r['self_ms']:8.1f}  {r['fn'][:38]:38s} {src}:{r['line']}  ← {' < '.join(r['stack'][:3])}")


if __name__ == "__main__":
    asyncio.run(main())
