"""Вариант C: HTML/CSS + SVG → скриншот headless-хромиумом (playwright уже стоит)."""
import datetime as dt
import math
import resource
import sys
import time

from cases import PALETTE

W, H = 1200, 750

CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; background:{PALETTE['bg']};
  font-family:'DejaVu Sans',sans-serif; color:{PALETTE['ink']}; padding:34px 44px; }}
h1 {{ font-size:34px; letter-spacing:-.5px; }}
.sub {{ font-size:24px; color:{PALETTE['ink_soft']}; margin-top:8px; }}
.legend {{ display:flex; gap:28px; margin-top:14px; font-size:22px; font-weight:700;
  color:{PALETTE['ink_soft']}; }}
.legend i {{ display:inline-block; width:30px; height:16px; margin-right:10px; border-radius:3px; }}
.cards {{ display:flex; gap:0; margin-top:70px; }}
.card {{ flex:1; padding-left:24px; }}
.card + .card {{ border-left:1px solid {PALETTE['border']}; }}
.card .v {{ font-size:84px; font-weight:700; line-height:1; }}
.card .l {{ font-size:22px; color:{PALETTE['ink_soft']}; margin-top:18px; }}
.card .n {{ font-size:20px; color:{PALETTE['ink_faint']}; margin-top:6px; }}
text {{ font-family:'DejaVu Sans',sans-serif; }}
.tick {{ fill:{PALETTE['ink_faint']}; font-size:22px; }}
.val {{ fill:{PALETTE['ink']}; font-size:22px; font-weight:700; }}
"""

PL, PR, PT, PB = 66, 0, 40, 56   # поле внутри svg


def _page(spec, body, legend=""):
    return f"""<!doctype html><meta charset="utf-8"><style>{CSS}</style>
<h1>{spec['title']}</h1><div class="sub">{spec['subtitle']}</div>{legend}{body}"""


def _legend(series):
    items = "".join(
        f'<span><i style="background:{s["color"]}"></i>{s["name"]}</span>' for s in series)
    return f'<div class="legend">{items}</div>'


def _svg_open(h):
    return f'<svg width="{W-88}" height="{h}" style="margin-top:18px">'


def _grid(ticks, y_of, w, fmt=lambda v: f"{v:g}"):
    out = []
    for t in ticks:
        y = y_of(t)
        out.append(f'<line x1="{PL}" y1="{y}" x2="{w}" y2="{y}" stroke="{PALETTE["border"]}"/>')
        out.append(f'<text class="tick" x="{PL-12}" y="{y+8}" text-anchor="end">{fmt(t)}</text>')
    return "".join(out)


def _nice(vmax, count=5):
    raw = vmax / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)
    ticks, v = [], 0.0
    while v <= vmax + step * .001:
        ticks.append(round(v, 10))
        v += step
    return ticks


def bars(spec, log=False):
    h = H - 250
    w = W - 88
    top, bot = PT, h - PB
    cats, series = spec["categories"], spec["series"]
    vmax = max(v for s in series for v in s["values"])
    if log:
        lo = 10 ** math.floor(math.log10(min(v for s in series for v in s["values"] if v > 0)))
        hi = 10 ** math.ceil(math.log10(vmax))
        y_of = lambda v: bot - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (bot - top)
        ticks = [lo * 10 ** i for i in range(int(math.log10(hi / lo)) + 1)]
    else:
        hi = _nice(vmax)[-1]
        y_of = lambda v: bot - v / hi * (bot - top)
        ticks = _nice(vmax)

    parts = [_svg_open(h), _grid(ticks, y_of, w)]
    band = (w - PL) / len(cats)
    bw = band * .8 / len(series)
    for ci, cat in enumerate(cats):
        cx = PL + band * (ci + .5)
        for si, s in enumerate(series):
            v = s["values"][ci]
            x0 = cx + (si - len(series) / 2) * bw + 3
            y = y_of(v)
            parts.append(f'<rect x="{x0}" y="{y}" width="{bw-6}" height="{bot-y}" fill="{s["color"]}"/>')
            parts.append(f'<text class="val" x="{x0+(bw-6)/2}" y="{y-12}" text-anchor="middle">{v:g}</text>')
        parts.append(f'<text class="tick" x="{cx}" y="{bot+34}" text-anchor="middle">{cat}</text>')
    thr = spec.get("threshold")
    if thr:
        y = y_of(thr["value"])
        parts.append(f'<line x1="{PL}" y1="{y}" x2="{w}" y2="{y}" stroke="{PALETTE["warn"]}" '
                     f'stroke-width="3" stroke-dasharray="10 8"/>')
        parts.append(f'<text class="val" x="{w-4}" y="{y-12}" text-anchor="end" '
                     f'fill="{PALETTE["warn"]}">{thr["label"]}</text>')
    parts.append(f'<line x1="{PL}" y1="{bot}" x2="{w}" y2="{bot}" stroke="{PALETTE["border"]}" stroke-width="2"/>')
    parts.append(f'<text class="tick" x="{PL-12}" y="{top-10}" text-anchor="end">{spec["unit"]}</text>')
    parts.append("</svg>")
    return _page(spec, "".join(parts), _legend(series))


def timeseries(spec):
    h = H - 250
    w = W - 88
    top, bot = PT, h - PB
    gap = dt.timedelta(minutes=spec["gap_minutes"])
    allt = [dt.datetime.fromisoformat(t) for s in spec["series"] for t, _ in s["points"]]
    t0, t1 = min(allt), max(allt)
    span = (t1 - t0).total_seconds()
    x_of = lambda t: PL + (t - t0).total_seconds() / span * (w - PL)
    y_of = lambda v: bot - v / 100 * (bot - top)

    parts = [_svg_open(h), _grid([0, 20, 40, 60, 80, 100], y_of, w)]
    for s in spec["series"]:
        seg, prev = [], None
        for t, v in s["points"]:
            cur = dt.datetime.fromisoformat(t)
            if prev is not None and cur - prev > gap:
                if len(seg) > 1:
                    parts.append(f'<polyline points="{" ".join(seg)}" fill="none" '
                                 f'stroke="{s["color"]}" stroke-width="3"/>')
                seg = []
            seg.append(f"{x_of(cur):.1f},{y_of(v):.1f}")
            prev = cur
        if len(seg) > 1:
            parts.append(f'<polyline points="{" ".join(seg)}" fill="none" stroke="{s["color"]}" stroke-width="3"/>')
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    while day <= t1:
        parts.append(f'<text class="tick" x="{x_of(day)}" y="{bot+34}" text-anchor="middle">{day.strftime("%d.%m")}</text>')
        day += dt.timedelta(days=1)
    parts.append(f'<line x1="{PL}" y1="{bot}" x2="{w}" y2="{bot}" stroke="{PALETTE["border"]}" stroke-width="2"/>')
    parts.append(f'<text class="tick" x="{PL-12}" y="{top-10}" text-anchor="end">{spec["unit"]}</text>')
    parts.append("</svg>")
    return _page(spec, "".join(parts), _legend(spec["series"]))


def scorecard(spec):
    cards = "".join(
        f'<div class="card"><div class="v" style="color:{m["color"]}">{m["value"]}</div>'
        f'<div class="l">{m["label"]}</div><div class="n">{m["note"]}</div></div>'
        for m in spec["metrics"])
    return _page(spec, f'<div class="cards">{cards}</div>')


def html_for(spec):
    k = spec["kind"]
    if k == "bars":
        return bars(spec)
    if k == "bars_log":
        return bars(spec, log=True)
    if k == "timeseries":
        return timeseries(spec)
    return scorecard(spec)


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    from cases import all_cases
    out = sys.argv[1]
    cases = all_cases()
    t_start = time.perf_counter()
    with sync_playwright() as p:
        t_pw = time.perf_counter()
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": W, "height": H})
        t_ready = time.perf_counter()
        print(f"playwright start: {(t_pw-t_start)*1000:.0f} ms, chromium launch+page: {(t_ready-t_pw)*1000:.0f} ms")
        for name, spec in cases.items():
            t0 = time.perf_counter()
            page.set_content(html_for(spec))
            page.screenshot(path=f"{out}/html_{name}.png")
            print(f"{name}: {(time.perf_counter()-t0)*1000:.0f} ms")
        rss_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        browser.close()
    print(f"python peak RSS: {rss_self:.0f} MB (хромиум — отдельные процессы, мерить снаружи)")
