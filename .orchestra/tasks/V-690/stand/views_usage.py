"""Stills of the expanded usage views (quota panel, 📊 analytics): python views_usage.py OUTDIR."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

RU_FORMAT = """(()=>{const t=setInterval(()=>{if(typeof window.fmtCost==='function'){window.fmtCost=v=>{v=Number(v)||0;return '$'+v.toLocaleString('ru-RU',{minimumFractionDigits:v<0.01?4:2,maximumFractionDigits:v<0.01?4:2})};clearInterval(t)}},0)})();"""

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1600, "height": 940}, device_scale_factor=2, locale="ru-RU")
    p.add_init_script("localStorage.setItem('orch_lang', 'ru')")
    p.add_init_script(RU_FORMAT)
    p.goto("http://127.0.0.1:8897/", wait_until="domcontentloaded")
    p.wait_for_timeout(7000)
    p.click("#usage-info-btn")
    p.wait_for_timeout(3000)
    p.screenshot(path=str(out / "dashboard-quota.png"))
    p.mouse.move(300, 700); p.wait_for_timeout(1000)
    p.click("#analytics-btn")
    p.wait_for_timeout(2500)
    p.click('[data-analytics-period="month"]')
    p.wait_for_timeout(2500)
    p.screenshot(path=str(out / "dashboard-spend.png"))
    b.close()
