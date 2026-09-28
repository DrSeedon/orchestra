# V-636: скриншоты итогового демо глазами владельца — вход, чат оркестратора, задачи, воркер.
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
env = dict(l.strip().split("=", 1) for l in open("/home/kesha/projects/seedon/secrets/reestr-demo-access.env")
           if "=" in l and not l.startswith("#"))
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU").new_page()
    pg.goto(env["DEMO_URL"]); pg.fill("input[name=username]", env["DEMO_DASHBOARD_USER"])
    pg.fill("input[name=password]", env["DEMO_DASHBOARD_PASSWORD"]); pg.click("button[type=submit]")
    pg.wait_for_timeout(8000)
    pg.screenshot(path=str(OUT / "1-вход-чат-оркестратора.png"))
    chat = pg.locator("#chat")
    for i in range(6):
        chat.evaluate(f"el => el.scrollTop = el.scrollHeight * {i} / 6")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=str(OUT / f"2-чат-{i+1}.png"))
    pg.get_by_text("ЗАДАЧИ", exact=True).first.click(); pg.wait_for_timeout(2500)
    pg.screenshot(path=str(OUT / "3-задачи.png"))
    pg.get_by_text("ФАЙЛЫ", exact=True).first.click(); pg.wait_for_timeout(1500)
    pg.locator("text=analitik >> visible=true").first.click(); pg.wait_for_timeout(5000)
    pg.screenshot(path=str(OUT / "4-воркер-analitik.png"))
    text = pg.inner_text("body")
    import re
    print("latin words in UI:", sorted(set(re.findall(r"\b[A-Za-z]{4,}\b", text)))[:80])
    b.close()
