"""#64 — вёрстка после замены Play-CDN Tailwind на собранный CSS: попиксельная сверка.

Живой сервер отдаёт статику из основного чекаута, поэтому «после» показывается подменой:
запрос за `tailwind.js` перехватывается и вместо компилятора отдаётся ТОТ ЖЕ код, что
делает шаблон после правки — вставка `<style>` с собранным CSS в том же месте разбора
документа (до `style.css`, как и `<link>` в новом шаблоне). Порядок важен: Play CDN
дописывал свои правила в head САМ, и если он делал это после `style.css`, приоритеты
каскада могли отличаться — именно это здесь и проверяется глазами и попиксельно.

Снимает по три состояния: список агентов, открытая панель задач, модалка аналитики.

Запуск: .venv/bin/python docs/tasks/64/measurements/visual_diff.py
"""
import asyncio, json, os, pathlib, sys

from PIL import Image, ImageChops
from playwright.async_api import async_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "57/measurements"))
import cpu_profile as CP

HERE = pathlib.Path(__file__).parent
BUILT = pathlib.Path(__file__).resolve().parents[4] / "app/static/css/vendor/tailwind.css"
STATES = ("agents", "tasks", "analytics")


async def shot(ctx, arm, css):
    page = await ctx.new_page()
    if css is not None:
        # ORDER=last — вставка ПОСЛЕ style.css, как это делал Play CDN (он дописывал свой
        # <style> в head в рантайме, то есть последним). ORDER=parse — на месте скрипта.
        append = ("addEventListener('DOMContentLoaded',function(){document.head.appendChild(s)})"
                  if os.environ.get("PERF64_ORDER", "last") == "last"
                  else "document.head.appendChild(s)")
        body = ("var s=document.createElement('style');"
                f"s.textContent={json.dumps(css)};{append};"
                "window.tailwind={config:{}};")
        await page.route("**/css/vendor/tailwind.js*",
                         lambda r: r.fulfill(status=200, content_type="application/javascript",
                                             body=body))
    await page.goto(CP.BASE + "/", wait_until="load")
    await asyncio.sleep(9)
    out = {}
    await page.screenshot(path=HERE / f"{arm}-agents.png")
    out["agents"] = HERE / f"{arm}-agents.png"

    await page.click('[data-left-tab="tasks"]')
    await asyncio.sleep(2.5)
    await page.screenshot(path=HERE / f"{arm}-tasks.png")
    out["tasks"] = HERE / f"{arm}-tasks.png"

    await page.click("#analytics-btn")
    await asyncio.sleep(4)
    await page.screenshot(path=HERE / f"{arm}-analytics.png")
    out["analytics"] = HERE / f"{arm}-analytics.png"
    await page.close()
    return out


async def main():
    css = BUILT.read_text()
    print(f"собранный CSS: {len(css)} байт")
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/perf64-visual", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(CP.BASE + "/login")
        await p.fill('input[name="username"]', CP.ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', CP.ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()
        await shot(ctx, "before", None)
        await shot(ctx, "control", None)   # второй заход БЕЗ правки — уровень шума живого контента
        await shot(ctx, "after", css)
        await ctx.close()

    for arm in ("control", "after"):
      print(f"\n--- before vs {arm} ---")
      for state in STATES:
        a = Image.open(HERE / f"before-{state}.png").convert("RGB")
        b = Image.open(HERE / f"{arm}-{state}.png").convert("RGB")
        if a.size != b.size:
            print(f"{state}: РАЗНЫЙ РАЗМЕР {a.size} vs {b.size}")
            continue
        diff = ImageChops.difference(a, b)
        box = diff.getbbox()
        px = sum(1 for p in diff.convert("L").getdata() if p > 12)
        total = a.size[0] * a.size[1]
        print(f"  {state:10s} различающихся пикселей: {px:8d} из {total} "
              f"({100 * px / total:5.2f}%)  область: {box}")
        if box:
            diff.save(HERE / f"diff-{arm}-{state}.png")


asyncio.run(main())
