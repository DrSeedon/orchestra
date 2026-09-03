"""Вариант B: Pillow вручную — ноль новых зависимостей, вся геометрия своя."""
import datetime as dt
import math
import sys

from PIL import Image, ImageDraw, ImageFont

from cases import PALETTE

W, H = 1200, 750
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
F_TITLE = ImageFont.truetype(FONT_B, 34)
F_SUB = ImageFont.truetype(FONT, 24)
F_TICK = ImageFont.truetype(FONT, 22)
F_VAL = ImageFont.truetype(FONT_B, 22)
F_BIG = ImageFont.truetype(FONT_B, 84)

PL, PR, PT, PB = 110, 40, 150, 70   # поле графика


def _canvas(spec):
    img = Image.new("RGB", (W, H), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    d.text((44, 34), spec["title"], font=F_TITLE, fill=PALETTE["ink"])
    d.text((44, 82), spec["subtitle"], font=F_SUB, fill=PALETTE["ink_soft"])
    return img, d


def _nice_ticks(vmax, count=5):
    """Округлённые деления 1/2/5 × 10^k — иначе подписи оси выглядят как мусор."""
    if vmax <= 0:
        return [0, 1]
    raw = vmax / count
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    ticks, v = [], 0.0
    while v <= vmax + step * 0.001:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _fmt(v):
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def _grid(d, ticks, y_of, unit):
    for t in ticks:
        y = y_of(t)
        d.line([(PL, y), (W - PR, y)], fill=PALETTE["border"], width=1)
        lbl = _fmt(t)
        w = d.textlength(lbl, font=F_TICK)
        d.text((PL - 14 - w, y - 13), lbl, font=F_TICK, fill=PALETTE["ink_faint"])
    d.text((44, PT - 34), unit, font=F_TICK, fill=PALETTE["ink_faint"])


def _legend(d, series, y=118):
    x = 44
    for s in series:
        d.rectangle([x, y + 8, x + 30, y + 24], fill=s["color"])
        d.text((x + 40, y + 2), s["name"], font=F_VAL, fill=PALETTE["ink_soft"])
        x += 40 + int(d.textlength(s["name"], font=F_VAL)) + 40


def bars(spec, path, log=False):
    img, d = _canvas(spec)
    cats, series = spec["categories"], spec["series"]
    vmax = max(v for s in series for v in s["values"])
    top, bot = PT, H - PB

    if log:
        lo = 10 ** math.floor(math.log10(min(v for s in series for v in s["values"] if v > 0)))
        hi = 10 ** math.ceil(math.log10(vmax))
        def y_of(v):
            v = max(v, lo)
            return bot - (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (bot - top)
        ticks = [lo * 10 ** i for i in range(int(math.log10(hi / lo)) + 1)]
    else:
        hi = _nice_ticks(vmax)[-1]
        def y_of(v):
            return bot - v / hi * (bot - top)
        ticks = _nice_ticks(vmax)

    _grid(d, ticks, y_of, spec["unit"])
    _legend(d, series)

    band = (W - PL - PR) / len(cats)
    bw = band * 0.8 / len(series)
    for ci, cat in enumerate(cats):
        cx = PL + band * (ci + 0.5)
        for si, s in enumerate(series):
            v = s["values"][ci]
            x0 = cx + (si - len(series) / 2) * bw
            y = y_of(v)
            d.rectangle([x0 + 3, y, x0 + bw - 3, bot], fill=s["color"])
            lbl = _fmt(v) if not log else f"{v:g}"
            lw = d.textlength(lbl, font=F_VAL)
            d.text((x0 + bw / 2 - lw / 2, y - 30), lbl, font=F_VAL, fill=PALETTE["ink"])
        cw = d.textlength(cat, font=F_TICK)
        d.text((cx - cw / 2, bot + 16), cat, font=F_TICK, fill=PALETTE["ink_faint"])

    thr = spec.get("threshold")
    if thr:
        y = y_of(thr["value"])
        for x in range(PL, W - PR, 18):
            d.line([(x, y), (x + 9, y)], fill=PALETTE["warn"], width=3)
        tw = d.textlength(thr["label"], font=F_VAL)
        d.text((W - PR - tw, y - 32), thr["label"], font=F_VAL, fill=PALETTE["warn"])

    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=2)
    img.save(path)


def timeseries(spec, path):
    img, d = _canvas(spec)
    top, bot = PT, H - PB
    gap = dt.timedelta(minutes=spec["gap_minutes"])
    allt = [dt.datetime.fromisoformat(t) for s in spec["series"] for t, _ in s["points"]]
    t0, t1 = min(allt), max(allt)
    span = (t1 - t0).total_seconds()

    def x_of(t):
        return PL + (t - t0).total_seconds() / span * (W - PL - PR)

    def y_of(v):
        return bot - v / 100 * (bot - top)

    _grid(d, [0, 20, 40, 60, 80, 100], y_of, spec["unit"])
    _legend(d, spec["series"])

    for s in spec["series"]:
        seg, prev = [], None
        for t, v in s["points"]:
            cur = dt.datetime.fromisoformat(t)
            if prev is not None and cur - prev > gap:
                if len(seg) > 1:
                    d.line(seg, fill=s["color"], width=3, joint="curve")
                elif len(seg) == 1:
                    d.ellipse([seg[0][0] - 4, seg[0][1] - 4, seg[0][0] + 4, seg[0][1] + 4], fill=s["color"])
                seg = []
            seg.append((x_of(cur), y_of(v)))
            prev = cur
        if len(seg) > 1:
            d.line(seg, fill=s["color"], width=3, joint="curve")

    day = t0.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    while day <= t1:
        x = x_of(day)
        lbl = day.strftime("%d.%m")
        lw = d.textlength(lbl, font=F_TICK)
        d.text((x - lw / 2, bot + 16), lbl, font=F_TICK, fill=PALETTE["ink_faint"])
        day += dt.timedelta(days=1)
    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=2)
    img.save(path)


def scorecard(spec, path):
    img, d = _canvas(spec)
    m = spec["metrics"]
    cw = (W - 88) / len(m)
    for i, met in enumerate(m):
        x = 44 + i * cw
        d.text((x, 250), met["value"], font=F_BIG, fill=met["color"])
        d.text((x, 380), met["label"], font=F_VAL, fill=PALETTE["ink_soft"])
        d.text((x, 415), met["note"], font=F_TICK, fill=PALETTE["ink_faint"])
        if i:
            d.line([(x - 20, 230), (x - 20, 450)], fill=PALETTE["border"], width=1)
    img.save(path)


def render(name, spec, path):
    if spec["kind"] == "bars":
        bars(spec, path)
    elif spec["kind"] == "bars_log":
        bars(spec, path, log=True)
    elif spec["kind"] == "timeseries":
        timeseries(spec, path)
    else:
        scorecard(spec, path)


if __name__ == "__main__":
    import time
    from cases import all_cases
    out = sys.argv[1]
    for name, spec in all_cases().items():
        t0 = time.perf_counter()
        render(name, spec, f"{out}/pil_{name}.png")
        print(f"{name}: {(time.perf_counter()-t0)*1000:.0f} ms")
