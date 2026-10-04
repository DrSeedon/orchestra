"""Capture dashboard views from the stand: python views.py OUTDIR [scale]."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 2
URL = "http://127.0.0.1:8897/"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1600, "height": 940}, device_scale_factor=scale)
    p.add_init_script("localStorage.setItem('orch_lang', 'en')")
    p.goto(URL, wait_until="domcontentloaded")
    p.wait_for_timeout(7000)
    p.screenshot(path=str(out / "hero.png"))
    chat = p.locator("#chat")
    chat.evaluate("el => el.scrollTop = 0")
    p.wait_for_timeout(800)
    p.screenshot(path=str(out / "chat-top.png"))
    p.click("[data-left-tab=tasks]")
    p.wait_for_timeout(1500)
    p.screenshot(path=str(out / "tasks.png"))
    p.click("[data-left-tab=jobs]")
    p.wait_for_timeout(1000)
    p.screenshot(path=str(out / "jobs.png"))
    p.click("[data-left-tab=files]")
    p.locator('.agent-item[data-agent-name="fix-double-charge"]').click()
    p.wait_for_timeout(2500)
    p.screenshot(path=str(out / "worker.png"))
    b.close()
