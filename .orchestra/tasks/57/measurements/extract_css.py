"""#57 — снять CSS, который Play-CDN Tailwind сгенерировал на живой странице.

Нужен для честной абляции: заглушка `tailwind_static` отдаёт ЭТОТ ЖЕ css статикой,
то есть работа стилей и раскладки сохраняется, убирается только JIT-компилятор и его
MutationObserver. Разница между базовым прогоном и такой заглушкой = цена именно
Play CDN, а не «страницы без стилей».
"""
import asyncio, os, pathlib

from playwright.async_api import async_playwright

BASE = os.environ.get("PERF57_BASE", "https://orchestra.seedon.ru")
OUT = pathlib.Path(__file__).parent / "tailwind-generated.css"
ENV = {}
for line in open("/home/kesha/orchestra/.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip().strip('"')

GRAB = """() => {
  // Play CDN складывает сгенерированное в <style> без href; свои файлы приходят как <link>
  const out = [];
  for (const s of document.styleSheets) {
    if (s.href) continue;
    try { for (const r of s.cssRules) out.push(r.cssText); } catch (e) {}
  }
  return out.join('\\n');
}"""


async def main():
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/perf57-css", headless=True, viewport={"width": 1600, "height": 1000})
        p = await ctx.new_page()
        await p.goto(BASE + "/login")
        await p.fill('input[name="username"]', ENV["DASHBOARD_USER"])
        await p.fill('input[name="password"]', ENV["DASHBOARD_PASSWORD"])
        await p.click('button[type="submit"], input[type="submit"]')
        await p.wait_for_load_state("load")
        await p.goto(BASE + "/", wait_until="load")
        await asyncio.sleep(14)
        css = await p.evaluate(GRAB)
        await ctx.close()
    OUT.write_text(css)
    print(f"{OUT}: {len(css)} байт, {css.count('{')} правил")


asyncio.run(main())
