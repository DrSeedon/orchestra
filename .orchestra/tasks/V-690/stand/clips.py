"""Record the stand in slow motion with named clip markers: python clips.py OUTDIR [SLOW].

Why slow motion: on this VPS a 2400×1410 capture takes 0.5–1.5 s, and the screencast API only
gives 1600×940. So the page runs SLOW times slower (its clocks, timers, rAF and CSS animations
are dilated), the recorder captures as fast as it can, and every logged time is converted back
to page time. At SLOW=10 that is ~7–15 frames per page-second at full resolution.

The mouse glides and clicks real dashboard UI, except Send: sending would make the stand try to
run a CLI, so /stand/live plays the scripted turn instead and the click is only logged.
Headless Chromium draws no cursor, so its track is logged (cursor.json) and the scene draws it.
Output: OUTDIR/frames/*.jpg, frames.txt (ffmpeg concat, page-time durations), marks.json, cursor.json.
"""
import asyncio
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

RU_FORMAT = """(()=>{const t=setInterval(()=>{if(typeof window.fmtCost==='function'){window.fmtCost=v=>{v=Number(v)||0;return '$'+v.toLocaleString('ru-RU',{minimumFractionDigits:v<0.01?4:2,maximumFractionDigits:v<0.01?4:2})};clearInterval(t)}},0)})();"""


out = Path(sys.argv[1]); (out / "frames").mkdir(parents=True, exist_ok=True)
SLOW = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
W, H, DPR = 1600, 940, 1.5
URL = "http://127.0.0.1:8897/"

DILATE = """(() => {
 const k = 1 / %s, pn = performance.now.bind(performance), p0 = pn(), D = Date, d0 = D.now();
 const vp = () => p0 + (pn() - p0) * k, vd = () => d0 + (D.now() - d0) * k;
 performance.now = vp;
 window.Date = class extends D { constructor(...a) { a.length ? super(...a) : super(vd()) } static now() { return vd() } };
 const raf = requestAnimationFrame.bind(window); window.requestAnimationFrame = cb => raf(() => cb(vp()));
 const st = setTimeout.bind(window), si = setInterval.bind(window);
 window.setTimeout = (f, d = 0, ...a) => st(f, d / k, ...a); window.setInterval = (f, d = 0, ...a) => si(f, d / k, ...a);
})();""" % SLOW

frames: list[tuple[float, str]] = []
marks: dict[str, list[float]] = {}
track: list[list] = []  # [wall time, x, y, clicked]
pos = [W / 2, H / 2]
recording = True


def now():
    return time.time()


async def main():
    global recording
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        page = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=DPR, locale="ru-RU")
        await page.add_init_script("localStorage.setItem('orch_lang', 'ru')")
        await page.add_init_script(RU_FORMAT)
        await page.add_init_script(DILATE)
        await page.goto(URL, wait_until="domcontentloaded")
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Animation.enable")
        await cdp.send("Animation.setPlaybackRate", {"playbackRate": 1 / SLOW})
        await page.wait_for_timeout(7000 * SLOW / 3)

        async def capture():
            while recording:
                at = now()
                r = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92, "optimizeForSpeed": True,
                                                              "clip": {"x": 0, "y": 0, "width": W, "height": H, "scale": DPR}})
                name = f"f{len(frames):05d}.jpg"
                (out / "frames" / name).write_bytes(base64.b64decode(r["data"]))
                frames.append(((at + now()) / 2, name))

        async def wait(ms):
            await page.wait_for_timeout(ms * SLOW)

        async def glide(x, y, ms=700):
            """Ease the cursor by wall clock; the logged track is what the scene replays."""
            x0, y0 = pos
            start = now()
            while True:
                p = min(1.0, (now() - start) * 1000 / (ms * SLOW))
                e = p * p * (3 - 2 * p)
                cx, cy = x0 + (x - x0) * e, y0 + (y - y0) * e
                await page.mouse.move(cx, cy)
                track.append([now(), round(cx, 1), round(cy, 1), 0])
                if p >= 1:
                    break
                await page.wait_for_timeout(40)
            pos[:] = [x, y]

        async def center(selector):
            for _ in range(30):  # the agent list re-renders on every status poll; retry a detached node
                bb = await page.locator(selector + " >> visible=true").first.bounding_box()
                if bb:
                    break
                await page.wait_for_timeout(100)
            return bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2

        async def click(selector, ms=700, settle=150):
            await glide(*await center(selector), ms=ms)
            await wait(settle)
            track.append([now(), *pos, 1])
            await page.mouse.down(); await page.mouse.up()

        def mark(name):
            marks.setdefault(name, []).append(now())
            print(name, round((now() - t0) / SLOW, 2), flush=True)

        await page.mouse.move(*pos)
        track.append([now(), *pos, 0])
        cap = asyncio.create_task(capture())
        t0 = now()
        await wait(600)

        mark("agents")
        await click('.agent-item[data-agent-name="fix-double-charge"]', ms=900)
        await wait(2600)
        await click('.agent-item[data-agent-name="e2e-tests"]', ms=600)
        await wait(1800)
        await click('.agent-item[data-agent-name="acme-orchestrator"]', ms=700)
        await wait(2200)
        mark("agents")

        mark("live")
        await click("#chat-input", ms=800)
        await page.locator("#chat-input").type("Тесты зелёные? Тогда мержи исправление двойного списания. Пока не выкатывай.",
                                               delay=30 * SLOW, timeout=0)
        await wait(300)
        sx, sy = await center("#send-btn")
        await glide(sx, sy, ms=500)
        track.append([now(), sx, sy, 1])
        await page.locator("#chat-input").fill("")
        await asyncio.to_thread(lambda: urllib.request.urlopen(urllib.request.Request(
            URL + f"stand/live?slow={SLOW}", method="POST"), timeout=5).read())
        await glide(W * 0.55, H * 0.55, ms=900)
        await wait(9500)
        mark("live")

        mark("tasks")
        await click("[data-left-tab=tasks]", ms=900)
        await wait(2600)
        mark("tasks")

        mark("quota")
        await click("#usage-info-btn", ms=1100, settle=350)
        await wait(1500)
        await glide(pos[0] - 30, pos[1] + 60, ms=120)  # straight into the panel: leaving the button closes it
        for sel in ('[data-usage-provider="claude"] [data-usage-history] svg',
                    '[data-usage-provider="codex"] [data-usage-history] svg'):
            loc = page.locator(sel)
            if await loc.count():
                bb = await loc.first.bounding_box()
                await glide(bb["x"] + bb["width"] * 0.15, bb["y"] + bb["height"] * 0.55, ms=600)
                await glide(bb["x"] + bb["width"] * 0.9, bb["y"] + bb["height"] * 0.55, ms=1300)
        older = '[data-usage-provider="claude"] [data-spark-nav="older"] >> nth=-1'
        if await page.locator(older).count():  # flip the Claude 7d chart to last week and back
            await click(older, ms=900)
            await wait(1300)
            newer = '[data-usage-provider="claude"] [data-spark-nav="newer"] >> nth=-1'
            if await page.locator(newer).count():
                await click(newer, ms=400)
                await wait(1000)
        await wait(600)
        mark("quota")
        await glide(W * 0.3, H * 0.7, ms=500)  # leaving the panel closes it
        await wait(1200)

        mark("spend")
        await click("#analytics-btn", ms=900, settle=250)
        await wait(1500)
        await glide(W * 0.5, H * 0.6, ms=500)
        await page.mouse.wheel(0, 520)
        await wait(2600)
        await click('[data-analytics-period="month"]', ms=900)
        await wait(2600)
        await click('[data-analytics-view="agents"]', ms=900)
        await wait(2600)
        mark("spend")
        recording = False
        await cap
        end = now()
        await b.close()
    return t0, end


t0, end = asyncio.run(main())
first = frames[0][0]
page_t = lambda t: round((t - first) / SLOW, 3)  # noqa: E731
lines = []
for (t, name), nxt in zip(frames, frames[1:] + [(end, None)]):
    lines += [f"file 'frames/{name}'", f"duration {max(0.01, (nxt[0] - t) / SLOW):.3f}"]
lines.append(f"file 'frames/{frames[-1][1]}'")
(out / "frames.txt").write_text("\n".join(lines) + "\n")
(out / "marks.json").write_text(json.dumps({k: [page_t(v[0]), page_t(v[1])] for k, v in marks.items()}, indent=1))
(out / "cursor.json").write_text(json.dumps([[page_t(t), x, y, c] for t, x, y, c in track]))
print(len(frames), "frames", round((end - t0) / SLOW, 1), "page s,", round(end - t0), "wall s")
