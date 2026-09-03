"""#64 — что именно разошлось в вёрстке: сравнение вычисленных стилей, а не пикселей.

Попиксельная сверка сказала «9.8% не совпало», но не сказала ЧТО. Здесь для одних и тех же
узлов (по устойчивому пути в дереве) снимаются `getComputedStyle` в обоих плечах и
сравниваются свойство за свойством.

Запуск: .venv/bin/python docs/tasks/64/measurements/computed_diff.py
"""
import asyncio, collections, json, os, pathlib, sys

from playwright.async_api import async_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "57/measurements"))
import cpu_profile as CP

BUILT = pathlib.Path(__file__).resolve().parents[4] / "app/static/css/vendor/tailwind.css"

PROPS = ["font-family", "font-size", "line-height", "font-weight", "color",
         "background-color", "margin-top", "margin-bottom", "padding-top", "padding-bottom",
         "padding-left", "padding-right", "border-radius", "letter-spacing", "gap",
         "display", "width", "height", "box-sizing", "border-top-width"]

GRAB = """(props) => {
  const path = (el) => {
    const parts = [];
    while (el && el !== document.body) {
      const p = el.parentElement;
      if (!p) break;
      parts.unshift(`${el.tagName}[${Array.prototype.indexOf.call(p.children, el)}]`);
      el = p;
    }
    return parts.join('/');
  };
  const out = {};
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    const k = path(el);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    const cs = getComputedStyle(el);
    const rec = {};
    for (const p of props) rec[p] = cs.getPropertyValue(p);
    rec.__cls = el.className && el.className.baseVal === undefined ? String(el.className).slice(0,80) : '';
    rec.__txt = (el.textContent || '').trim().slice(0, 40);
    out[k] = rec;
  }
  return out;
}"""


async def grab(ctx, css):
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
    data = await page.evaluate(GRAB, PROPS)
    await page.close()
    return data


async def main():
    css = BUILT.read_text()
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/perf64-computed", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(CP.BASE + "/login")
        await p.fill('input[name="username"]', CP.ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', CP.ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.close()
        before = await grab(ctx, None)
        control = await grab(ctx, None)
        after = await grab(ctx, css)
        await ctx.close()

    for tag, other in (("КОНТРОЛЬ (без правки, второй заход)", control), ("ПОСЛЕ ПРАВКИ", after)):
        print(f"\n=== {tag} ===")
        _cmp(before, other)


def _cmp(before, after):
    common = set(before) & set(after)
    print(f"узлов сравнено: {len(common)} (было {len(before)}, стало {len(after)})")
    per_prop = collections.Counter()
    examples = collections.defaultdict(list)
    for k in common:
        for p in PROPS:
            a, b = before[k].get(p), after[k].get(p)
            if a != b:
                per_prop[p] += 1
                if len(examples[p]) < 4:
                    examples[p].append(f"{a!r} → {b!r}  cls={after[k].get('__cls')!r} txt={after[k].get('__txt')!r}")
    if not per_prop:
        print("расхождений вычисленных стилей НЕТ")
        return
    print("\nрасхождения по свойствам:")
    for p, n in per_prop.most_common():
        print(f"  {p:20s} {n:5d} узлов")
        for e in examples[p]:
            print(f"      {e}")


asyncio.run(main())
