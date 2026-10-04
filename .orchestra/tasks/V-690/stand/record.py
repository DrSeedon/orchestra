"""Record the stand's 'live' turn as lossless frames (CDP screencast): python record.py OUTDIR.

Frames arrive only when the page changes; frames.txt is an ffmpeg concat list with real durations.
"""
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

RU_FORMAT = """(()=>{const t=setInterval(()=>{if(typeof window.fmtCost==='function'){window.fmtCost=v=>{v=Number(v)||0;return '$'+v.toLocaleString('ru-RU',{minimumFractionDigits:v<0.01?4:2,maximumFractionDigits:v<0.01?4:2})};clearInterval(t)}},0)})();"""

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
W, H = 1280, 800
DPR = 1.5
URL = "http://127.0.0.1:8897/"
frames: list[tuple[float, str]] = []


def live():
    urllib.request.urlopen(urllib.request.Request(URL + "stand/live", method="POST"), timeout=5).read()


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=DPR, locale="ru-RU")
    page.add_init_script("localStorage.setItem('orch_lang', 'ru')")
    page.add_init_script(RU_FORMAT)
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    cdp = page.context.new_cdp_session(page)

    def on_frame(ev):
        name = f"f{len(frames):05d}.png"
        (out / name).write_bytes(base64.b64decode(ev["data"]))
        frames.append((ev["metadata"]["timestamp"], name))
        cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    cdp.on("Page.screencastFrame", on_frame)
    cdp.send("Page.startScreencast", {"format": "png", "maxWidth": int(W * DPR), "maxHeight": int(H * DPR), "everyNthFrame": 1})
    t0 = time.time()
    page.wait_for_timeout(2500)
    box = page.locator("#chat-input")
    box.click()
    box.type("Тесты зелёные? Тогда мержи исправление двойного списания. Пока не выкатывай.", delay=38)
    page.wait_for_timeout(500)
    box.fill("")
    live()
    page.wait_for_timeout(11500)
    page.click("[data-left-tab=tasks]")
    page.wait_for_timeout(3000)
    page.wait_for_timeout(100)
    end = time.time()
    cdp.send("Page.stopScreencast")
    b.close()

lines = []
for (t, name), nxt in zip(frames, frames[1:] + [(frames[0][0] + (end - t0) + 1, None)]):
    lines += [f"file '{name}'", f"duration {max(0.02, nxt[0] - t):.3f}"]
lines.append(f"file '{frames[-1][1]}'")
(out / "frames.txt").write_text("\n".join(lines) + "\n")
print(len(frames), "frames", round(end - t0, 1), "s")
