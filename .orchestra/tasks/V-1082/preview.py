"""Reproducible offline preview. All values are invented; no DB/providers/Telegram."""
import asyncio
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app import charts, limits_card as card

OUT = Path(__file__).resolve().parent
NOW = dt.datetime(2026, 10, 25, 10, 0, tzinfo=dt.timezone.utc)


def iso(minutes):
    return (NOW + dt.timedelta(minutes=minutes)).isoformat()


def window(key, value, minutes, reset):
    return dict(id=key, utilization=value, window_minutes=minutes, resets_at=iso(reset))


def samples():
    rows = []
    for ago in [*range(2880, 0, -30), 5]:
        if 850 < ago < 1150:  # a real hole in the synthetic fixture
            continue
        short_reset = 120 - ((ago + 120) // 300) * 300
        short_elapsed = (300 - (short_reset + ago)) / 300
        five = round(short_elapsed * 65, 1)
        week = round(38 + (2880 - ago) / 2880 * 42, 1)
        providers = {
            "anthropic": {"windows": [window("five_hour", five, 300, short_reset),
                                       window("seven_day", week, 10080, 5760)]},
            "codex": {"windows": [window("primary", five * .7, 300, short_reset),
                                   window("secondary", week * .78, 10080, 4320)]},
        }
        if ago <= 120 and ago != 60:  # missing Spark in one stored observation
            providers["codex_spark"] = {"windows": [window("primary", five * .4, 300, 120)]}
        if ago == 120:  # one stale Grok measurement, no zero-filled continuation
            providers["grok"] = {"windows": [window("primary", 32, 120, 0)]}
        rows.append(dict(ts=iso(-ago), providers=providers))
    return dict(rows=rows, step_minutes=30)


def fixture():
    history = samples()
    latest = history["rows"][-1]["providers"]
    claude = latest["anthropic"]["windows"]
    codex = latest["codex"]["windows"]
    spark = latest["codex_spark"]["windows"]
    usage = {
        "anthropic": {"five_hour": claude[0], "seven_day": claude[1]},
        "codex": {"primary": codex[0], "secondary": codex[1], "spark": {"primary": spark[0]}},
        "grok": {},
        "quota_headroom": dict(rate=.132, windows_left=1.52, available_pct=100-five(claude),
                               locked_pct=0),
    }
    return usage, history


def five(claude):
    return claude[0]["utilization"]


async def main():
    import app
    print(f"Imported app: {app.__file__}")
    usage, history = fixture()
    (OUT / "synthetic-data.json").write_text(json.dumps(dict(
        synthetic=True, now=NOW.isoformat(), usage=usage, history=history,
    ), indent=2, ensure_ascii=False))
    charts.CHART_DIR = OUT
    # Production HTML and PNG renderer, changing only output filenames and adding a demo label.
    original_build = card.build_html
    def labeled(data):
        return original_build(data).replace('<div class="head">',
            '<div class="history-note">СИНТЕТИЧЕСКИЙ ПРИМЕР · все значения вымышлены</div><div class="head">', 1)
    card.build_html = labeled
    for name, missing in (("synthetic-preview", False), ("synthetic-missing", True)):
        if missing:
            usage["codex"]["spark"] = {}
            for row in history["rows"]:
                row["providers"].pop("codex_spark", None)
                row["providers"].pop("grok", None)
        charts.new_chart_path = lambda: OUT / f"{name}.png"
        source = card.build_html(card.collect(usage, now=NOW, history=history))
        path = await card.render_limits_card(usage, now=NOW, history=history)
        (OUT / f"{name}.html").write_text(source)
        # Read actual browser layout; all resources must remain local.
        page = await card._renderer_browser.new_page(viewport={"width": 900, "height": 1200})
        errors = []
        requests = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: requests.append(req.url))
        await page.goto((OUT / f"{name}.html").as_uri())
        layout = await page.evaluate('''() => ({
          width: document.documentElement.scrollWidth, height: document.body.scrollHeight,
          charts: document.querySelectorAll('.history svg').length,
          overflows: [...document.querySelectorAll('.pool .top, .pool .bot')].filter(e => e.scrollWidth > e.clientWidth).map(e => e.textContent),
        })''')
        assert layout["width"] == 900 and not layout["overflows"]
        assert layout["height"] + 900 <= 10000 and layout["height"] / 900 <= 20
        assert not errors and not [url for url in requests if not url.startswith('file:')]
        if not missing:
            await page.set_viewport_size({'width': 900, 'height': layout['height']})
            bounds = await page.locator('.pools').bounding_box()
            await page.screenshot(path=str(OUT / 'synthetic-history-detail.png'), clip={
                'x': 25, 'y': bounds['y'], 'width': 850, 'height': 750,
            })
        print(name, json.dumps(dict(layout=layout, errors=errors,
              remote_requests=[url for url in requests if not url.startswith('file:')]), ensure_ascii=False))
        await page.close()
        print(Path(path).name, hashlib.sha256(Path(path).read_bytes()).hexdigest())
    await card.shutdown_renderer()


if __name__ == "__main__":
    asyncio.run(main())
