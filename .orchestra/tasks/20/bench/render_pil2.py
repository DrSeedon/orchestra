"""Pillow, вторая итерация: размеры под телефон.

Что изменено против render_pil.py и почему — по результату просмотра в 340 px:
  * шрифты крупнее в 1.5-1.8×: подписи 22 px на холсте 1200 px в пузыре ТГ дают ~6 pt;
  * у столбцов убрана ось Y — значение подписано на самом столбце, ось дублировала его;
  * провалы в ряду показаны ПОЛОСАМИ, а не только разрывом линии: разрыв в 340 px не виден;
  * ряд прорежен по пикселям — 1751 точка на 1000 px рисует шум, из которого не читается ничего.
"""
import datetime as dt
import math
import sys

from PIL import Image, ImageDraw, ImageFont

from cases import PALETTE

W, H = 1200, 750
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
F_TITLE = ImageFont.truetype(FONT_B, 44)
F_SUB = ImageFont.truetype(FONT, 32)
F_VAL = ImageFont.truetype(FONT_B, 34)
F_CAT = ImageFont.truetype(FONT, 30)
F_LEG = ImageFont.truetype(FONT_B, 28)

PL, PR, PT, PB = 40, 40, 210, 96

_VAL_LADDER = [ImageFont.truetype(FONT_B, s) for s in (34, 30, 26, 22)]


def _fit(d, text, width):
    """Самый крупный кегль из лесенки, при котором подпись влезает в столбец."""
    for f in _VAL_LADDER:
        if d.textlength(text, font=f) <= width:
            return f
    return _VAL_LADDER[-1]


def _canvas(spec):
    img = Image.new("RGB", (W, H), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    d.text((44, 36), spec["title"], font=F_TITLE, fill=PALETTE["ink"])
    d.text((44, 96), spec["subtitle"], font=F_SUB, fill=PALETTE["ink_soft"])
    return img, d


def _legend(d, series, y):
    x = 44
    for s in series:
        d.rectangle([x, y + 6, x + 34, y + 26], fill=s["color"])
        d.text((x + 46, y), s["name"], font=F_LEG, fill=PALETTE["ink_soft"])
        x += 46 + int(d.textlength(s["name"], font=F_LEG)) + 46


def bars(spec, path):
    img, d = _canvas(spec)
    _legend(d, spec["series"], 150)
    cats, series = spec["categories"], spec["series"]
    vmax = max(v for s in series for v in s["values"])
    top, bot = PT, H - PB
    band = (W - PL - PR) / len(cats)
    bw = band * 0.76 / len(series)
    for ci, cat in enumerate(cats):
        cx = PL + band * (ci + 0.5)
        for si, s in enumerate(series):
            v = s["values"][ci]
            x0 = cx + (si - len(series) / 2) * bw
            y = bot - v / vmax * (bot - top)
            d.rectangle([x0 + 4, y, x0 + bw - 4, bot], fill=s["color"])
            lbl = f"{v:g}"
            font = _fit(d, lbl, bw - 6)   # подпись шире столбца налезает на соседнюю
            lw = d.textlength(lbl, font=font)
            d.text((x0 + bw / 2 - lw / 2, y - 44), lbl, font=font, fill=PALETTE["ink"])
        cw = d.textlength(cat, font=F_CAT)
        d.text((cx - cw / 2, bot + 18), cat, font=F_CAT, fill=PALETTE["ink_faint"])
    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=3)
    img.save(path)


def timeseries(spec, path):
    top, bot = PT, H - PB
    gap = dt.timedelta(minutes=spec["gap_minutes"])
    allt = [dt.datetime.fromisoformat(t) for s in spec["series"] for t, _ in s["points"]]
    t0, t1 = min(allt), max(allt)
    span = (t1 - t0).total_seconds()
    x_of = lambda t: PL + (t - t0).total_seconds() / span * (W - PL - PR)
    y_of = lambda v: bot - v / 100 * (bot - top)

    # провалы считаем ДО отрисовки: подпись обязана описывать нарисованное окно,
    # а не всю историю — иначе картинка утверждает то, чего в ней нет
    prev, gaps = None, []
    for t, _ in spec["series"][0]["points"]:
        cur = dt.datetime.fromisoformat(t)
        if prev is not None and cur - prev > gap:
            gaps.append((prev, cur))
        prev = cur
    longest = max(gaps, key=lambda g: g[1] - g[0]) if gaps else None
    days = round(span / 86400)
    sub = spec["subtitle"]
    if longest:
        mins = (longest[1] - longest[0]).total_seconds() / 60
        sub = (f"{len(gaps)} провалов в снимках за {days} суток, "
               f"самый длинный {int(mins//60)} ч {int(mins%60)} мин")
    img, d = _canvas({**spec, "subtitle": sub})

    for a, b in gaps:
        x0, x1 = x_of(a), x_of(b)
        d.rectangle([x0, top, max(x1, x0 + 2), bot], fill="#2a1520")
    if longest:
        d.rectangle([x_of(longest[0]), top, x_of(longest[1]), bot], fill="#4a1d2e")
    _legend(d, list(spec["series"]) + [{"name": "нет данных", "color": "#4a1d2e"}], 150)

    for tick in (0, 50, 100):
        y = y_of(tick)
        d.line([(PL, y), (W - PR, y)], fill=PALETTE["border"], width=1)
        d.text((PL + 6, y - 36), f"{tick}%", font=F_CAT, fill=PALETTE["ink_faint"])

    for s in spec["series"]:
        seg, prev = [], None
        for t, v in s["points"]:
            cur = dt.datetime.fromisoformat(t)
            if prev is not None and cur - prev > gap:
                if len(seg) > 1:
                    d.line(seg, fill=s["color"], width=4, joint="curve")
                seg = []
            seg.append((x_of(cur), y_of(v)))
            prev = cur
        if len(seg) > 1:
            d.line(seg, fill=s["color"], width=4, joint="curve")

    day = t0.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    while day <= t1:
        x = x_of(day)
        lbl = day.strftime("%d.%m")
        lw = d.textlength(lbl, font=F_CAT)
        d.text((x - lw / 2, bot + 18), lbl, font=F_CAT, fill=PALETTE["ink_faint"])
        day += dt.timedelta(days=2)
    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=3)
    img.save(path)


if __name__ == "__main__":
    import time
    from cases import all_cases
    out = sys.argv[1]
    cases = all_cases()
    for name, fn in (("c1_bars", bars), ("c3_series", timeseries)):
        t0 = time.perf_counter()
        fn(cases[name], f"{out}/pil2_{name}.png")
        print(f"{name}: {(time.perf_counter()-t0)*1000:.0f} ms")
