"""Screenshot the stand: python shot.py OUT.png [agent] [width height]."""
import sys
from playwright.sync_api import sync_playwright

RU_FORMAT = """(()=>{const t=setInterval(()=>{if(typeof window.fmtCost==='function'){window.fmtCost=v=>{v=Number(v)||0;return '$'+v.toLocaleString('ru-RU',{minimumFractionDigits:v<0.01?4:2,maximumFractionDigits:v<0.01?4:2})};clearInterval(t)}},0)})();"""
out = sys.argv[1]; agent = sys.argv[2] if len(sys.argv) > 2 else ""
w, h = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1600, 900)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
    errors = []
    p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    p.on("requestfailed", lambda r: errors.append("FAILED " + r.url))
    p.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    p.add_init_script("localStorage.setItem('orch_lang', 'ru')")
    p.add_init_script(RU_FORMAT)
    p.goto("http://127.0.0.1:8897/", wait_until="domcontentloaded")
    p.wait_for_timeout(7000)
    p.screenshot(path=out)
    print("\n".join(errors[:30]))
    b.close()
