"""#32 — сколько стоит открытие дашборда со стороны БРАУЗЕРА (не curl).

Меряет живой :8888 (сервис от 13:48, фронт из main) настоящим Chromium:
навигация, все ресурсы с байтами провода, FCP/LCP, длинные задачи главного потока,
момент появления списка агентов и момента появления чата.

Два плеча в одном окне:
  cold — чистый профиль (пустая IndexedDB, пустой HTTP-кеш) = первый заход
  warm — тот же профиль второй раз (F5) = обычный день юзера

Запуск: /home/kesha/orchestra/.venv/bin/python docs/tasks/32/measurements/browser_load.py <label> [wait_s]
"""
import asyncio, json, os, pathlib, sys, time

from playwright.async_api import async_playwright

# ВХОД ТОТ ЖЕ, ЧТО У ЮЗЕРА: домен + nginx (HTTP/2, gzip). Прямой :8888 идёт в обход
# сжатия и даёт завышенные байты — так был испорчен первый прогон.
BASE = os.environ.get("PERF32_BASE", "https://orchestra.seedon.ru")
ENV = {}
_env_file = os.environ.get("PERF32_ENV", "/home/kesha/orchestra/.env")
if os.path.exists(_env_file):
    for line in open(_env_file):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip().strip('"')
# на чужой машине .env нет — креды приходят переменными окружения
for k in ("DASHBOARD_USER", "DASHBOARD_PASSWORD"):
    if os.environ.get(k):
        ENV[k] = os.environ[k]

LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
OUT = pathlib.Path(__file__).parent / f"browser-{LABEL}.json"

PROBE = """() => {
  const nav = performance.getEntriesByType('navigation')[0];
  const res = performance.getEntriesByType('resource').map(r => ({
    name: r.name, type: r.initiatorType, start: +r.startTime.toFixed(1),
    end: +r.responseEnd.toFixed(1), dur: +r.duration.toFixed(1),
    wire: r.transferSize, decoded: r.decodedBodySize}));
  const paint = {};
  for (const p of performance.getEntriesByType('paint')) paint[p.name] = +p.startTime.toFixed(1);
  return {
    nav: nav ? {ttfb: +(nav.responseStart - nav.requestStart).toFixed(1),
                htmlWire: nav.transferSize, htmlDecoded: nav.decodedBodySize,
                domInteractive: +nav.domInteractive.toFixed(1),
                domContentLoaded: +nav.domContentLoadedEventEnd.toFixed(1),
                load: +nav.loadEventEnd.toFixed(1)} : null,
    paint, res,
    longtasks: window.__lt || [], lcp: window.__lcp || null,
    marks: window.__marks || {},
    cores: navigator.hardwareConcurrency,
  };
}"""

INIT = """
window.__lt = []; window.__marks = {}; window.__lcp = null;
try { new PerformanceObserver(l => { for (const e of l.getEntries())
        window.__lt.push({start: +e.startTime.toFixed(1), dur: +e.duration.toFixed(1)}); })
      .observe({type: 'longtask', buffered: true}); } catch (e) {}
try { new PerformanceObserver(l => { const e = l.getEntries().pop();
        if (e) window.__lcp = +e.startTime.toFixed(1); })
      .observe({type: 'largest-contentful-paint', buffered: true}); } catch (e) {}
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
  // 20 СТРОК журнала дают ~11-12 узлов (tool_result вливается в узел инструмента),
  // поэтому первый кадр ловит метка на 10, а не на 20.
  mark('chat10', '#chat > *', 10);
  mark('chat20', '#chat > *', 20);
});
"""


def loadavg():
    return open("/proc/loadavg").read().split()[:3]


async def arm(ctx, label):
    page = await ctx.new_page()
    # PERF32_APPJS=<файл> — подменить app.js версией из чужой ветки, не трогая чекаут
    override = os.environ.get("PERF32_APPJS")
    hits = []
    if override:
        body = pathlib.Path(override).read_text()
        if "_replayingHistory" not in body:      # маркер ветки: нет его — подмена бессмысленна
            raise SystemExit(f"{override}: маркера _replayingHistory нет, это не та версия")

        async def _serve(route):
            hits.append(1)
            await route.fulfill(status=200, content_type="application/javascript", body=body)

        await page.route("**/static/js/app.js*", _serve)
    await page.add_init_script(INIT)
    wire = []
    page.on("response", lambda r: wire.append(r))
    t0 = time.time()
    await page.goto(BASE + "/", wait_until="load")
    await asyncio.sleep(WAIT)
    data = await page.evaluate(PROBE)
    data["label"] = label
    data["wallclock_s"] = round(time.time() - t0, 2)
    data["loadavg"] = loadavg()
    # SSE-потоки не попадают в resource timing как завершённые — считаем их отдельно
    # r.body() на открытом SSE висит вечно — байты потока меряются отдельно, curl'ом
    data["sse"] = [r.url for r in wire if "/stream" in r.url]
    data["urls"] = [r.url for r in wire]
    data["responses"] = len(wire)
    data["appjs_override_hits"] = len(hits)
    if override and not hits:
        raise SystemExit("подмена app.js не сработала — цифры были бы от основного чекаута")
    await page.close()
    return data


async def main():
    # НЕ в /tmp по умолчанию на чужой машине: там tmpfs, то есть RAM юзера
    profile = pathlib.Path(os.environ.get("PERF32_PROFILE_DIR", "/tmp")) / f"perf32-profile-{LABEL}"
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(profile), headless=True, viewport={"width": 1600, "height": 1000})
        # логин один раз, в чистом профиле
        p = await ctx.new_page()
        await p.goto(BASE + "/login")
        await p.fill('input[name="username"]', ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()

        # три плеча: первый заход, второй (зеркало заполнено синхронизацией),
        # третий (в зеркале уже лежит добранная страница — если добор её пишет)
        arms = [await arm(ctx, "cold")]
        if not os.environ.get("PERF32_ONLY_COLD"):
            arms += [await arm(ctx, "warm1"), await arm(ctx, "warm2")]
        await ctx.close()
    OUT.write_text(json.dumps({a["label"]: a for a in arms}, ensure_ascii=False, indent=1))
    for d in arms:
        r = d["res"]
        tot = sum(x["wire"] for x in r)
        print(f"\n[{d['label']}] load={d['loadavg']} responses={d['responses']} "
              f"resources={len(r)} wire={tot/1024:.0f}KB")
        print(f"  nav: {d['nav']}")
        print(f"  paint: {d['paint']} lcp={d['lcp']} marks={d['marks']}")
        lt = d["longtasks"]
        print(f"  longtasks: n={len(lt)} total={sum(x['dur'] for x in lt):.0f}ms "
              f"max={max([x['dur'] for x in lt], default=0):.0f}ms")
        agg = {}
        for x in r:
            key = x["name"].split("?")[0].replace("https://orchestra.seedon.ru", "")
            a = agg.setdefault(key, [0, 0])
            a[0] += 1
            a[1] += x["wire"]
        print("  по эндпоинтам (n, КБ):")
        for k, (n, b) in sorted(agg.items(), key=lambda kv: -kv[1][1])[:12]:
            print(f"   {n:3d}× {b/1024:8.1f}KB  {k}")
        for x in sorted(r, key=lambda x: -x["wire"])[:8]:
            print(f"   {x['wire']/1024:8.1f}KB {x['start']:8.0f}→{x['end']:8.0f}ms  {x['name'][-70:]}")
        for s in d["sse"]:
            print(f"   SSE {s[-90:]}")


asyncio.run(main())
