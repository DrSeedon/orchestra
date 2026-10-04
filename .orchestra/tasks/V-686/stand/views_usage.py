"""Stills of the expanded usage views (quota panel, 📊 analytics): python views_usage.py OUTDIR."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_fix import EN_LOCALE

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1600, "height": 940}, device_scale_factor=2)
    p.add_init_script("localStorage.setItem('orch_lang', 'en')")
    p.add_init_script(EN_LOCALE)
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
