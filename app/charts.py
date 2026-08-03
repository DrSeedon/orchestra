"""Картинки для агентских отчётов: данные на входе, PNG на выходе.

Рисуем Pillow вручную — замер в docs/tasks/20/research.md: с телефона три движка
(matplotlib, Pillow, HTML+chromium) неразличимы, поэтому решает цена, а Pillow дешевле
остальных и не тащит зависимостей.

Главное правило модуля: числовую строку под заголовком считает ЭТОТ КОД по тем данным,
которые реально нарисованы. Вызывающий её не передаёт и приписать картинке несуществующее
число не может.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 750
PL, PR, PT, PB = 40, 40, 210, 96          # поле графика
KINDS = ("bars", "bars_log", "series", "cards")
CHART_DIR = Path(__file__).resolve().parent.parent / "data" / "charts"
_KEEP = 200                                # сколько картинок держим в каталоге

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_REG, _BOLD = _FONT_DIR / "DejaVuSans.ttf", _FONT_DIR / "DejaVuSans-Bold.ttf"

PALETTE = {
    "bg": "#0a0e17", "border": "#334155", "ink": "#e2e8f0",
    "ink_soft": "#a6b3c6", "ink_faint": "#8595ab",
    "accent": "#818cf8", "accent_alt": "#38bdf8",
    "ok": "#22c55e", "warn": "#eab308", "danger": "#ef4444",
}
_TONES = {"good": PALETTE["ok"], "bad": PALETTE["danger"], "neutral": PALETTE["ink_soft"]}
_CYCLE = (PALETTE["accent_alt"], PALETTE["warn"], PALETTE["accent"])
_GAP_FILL, _GAP_FILL_MAX = "#2a1520", "#4a1d2e"

# потолки читаемости: в пузыре Telegram (~340 pt) больше крупных элементов не разбирается
MAX_CATEGORIES, MAX_BAR_SERIES, MAX_LINES, MAX_POINTS, MAX_CARDS = 8, 3, 3, 50_000, 4


class ChartError(ValueError):
    """Данные нарисовать нельзя. Текст объясняет, что чинить."""


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _BOLD if bold else _REG
    if not path.exists():
        raise ChartError(f"нет файла шрифта {path} — без него подписи не нарисовать")
    return ImageFont.truetype(str(path), size)


# ── числа и подписи ───────────────────────────────────────────────────────────

def _num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return f"{int(v):,}".replace(",", " ")
    return f"{v:.3g}"


def _ratio(a: float, b: float) -> str | None:
    if a <= 0 or b <= 0:
        return None
    k = max(a, b) / min(a, b)
    if k < 1.05:
        return None
    return f"{k:.0f}× " if k >= 100 else f"{k:.1f}× "


def _fact_bars(categories: list[str], series: list[dict], unit: str) -> str:
    """Строка под заголовком для столбцов — считается по нарисованным значениям."""
    u = f" {unit}" if unit else ""
    if len(series) == 2:
        a_vals, b_vals = series[0]["values"], series[1]["values"]
        best, best_k = 0, -1.0
        for i, (a, b) in enumerate(zip(a_vals, b_vals)):
            k = max(a, b) / min(a, b) if a > 0 and b > 0 else abs(a - b)
            if k >= best_k:          # >= : при равных отношениях берём последнюю категорию
                best, best_k = i, k
        a, b = a_vals[best], b_vals[best]
        tail = _ratio(a, b)
        tail = f" ({tail}{'меньше' if b < a else 'больше'})" if tail else ""
        return f"{categories[best]}: {_num(a)} → {_num(b)}{u}{tail}"
    top = max(((v, c) for s in series for v, c in zip(s["values"], categories)),
              key=lambda p: p[0])
    return f"максимум: {top[1]} {_num(top[0])}{u}".rstrip()


def _human_span(seconds: float) -> str:
    if seconds >= 2 * 86400:
        return f"{round(seconds / 86400)} суток"
    if seconds >= 2 * 3600:
        return f"{round(seconds / 3600)} часов"
    return f"{round(seconds / 60)} минут"


def _human_gap(seconds: float) -> str:
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    return f"{h} ч {m} мин" if h else f"{m} мин"


def _fact_series(points: list[dt.datetime], gaps: list[tuple], span: float) -> str:
    head = f"{len(points)} точек за {_human_span(span)}"
    if not gaps:
        return f"{head}, провалов нет"
    longest = max((b - a).total_seconds() for a, b in gaps)
    return f"{head}, {len(gaps)} провалов, самый длинный {_human_gap(longest)}"


# ── валидация ─────────────────────────────────────────────────────────────────

def _check_values(values, where: str, allow_zero: bool = True) -> None:
    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ChartError(f"{where}[{i}] = {v!r} — не число")
        if math.isnan(v) or math.isinf(v):
            raise ChartError(f"{where}[{i}] = {v} — не конечное число")
        if v < 0 and not allow_zero:
            raise ChartError(
                f"{where}[{i}] = {v} — на логарифмической шкале отрицательных нет; "
                f"возьми kind='bars'")


def _validate_bars(data: dict, log: bool) -> tuple[list[str], list[dict], str]:
    cats = data.get("categories") or []
    series = data.get("series") or []
    if not cats:
        raise ChartError("нет categories — рисовать нечего")
    if len(cats) == 1:
        raise ChartError(
            "одна категория — это не график, а два числа; возьми kind='cards'")
    if len(cats) > MAX_CATEGORIES:
        raise ChartError(
            f"{len(cats)} категорий при потолке {MAX_CATEGORIES}: с телефона столько "
            f"столбцов не читается, сгруппируй данные")
    if not series:
        raise ChartError("нет series — рисовать нечего")
    if len(series) > MAX_BAR_SERIES:
        raise ChartError(f"{len(series)} серий при потолке {MAX_BAR_SERIES}")
    for s in series:
        vals = s.get("values")
        if not vals:
            raise ChartError(f"серия {s.get('name')!r} без values")
        if len(vals) != len(cats):
            raise ChartError(
                f"серия {s.get('name')!r}: {len(vals)} значений на {len(cats)} категорий")
        _check_values(vals, f"series[{s.get('name')!r}].values", allow_zero=not log)
    return cats, series, data.get("unit", "")


def _parse_ts(raw) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        raise ChartError(f"метку времени {raw!r} не разобрать, нужен ISO-8601")


def _validate_series(data: dict) -> tuple[list[dict], str]:
    series = data.get("series") or []
    if not series:
        raise ChartError("нет series — рисовать нечего")
    if len(series) > MAX_LINES:
        raise ChartError(f"{len(series)} линий при потолке {MAX_LINES}: "
                         f"больше трёх на телефоне сливаются")
    out = []
    for s in series:
        raw = s.get("points") or []
        if len(raw) < 2:
            raise ChartError(f"линия {s.get('name')!r}: точек {len(raw)}, нужно минимум 2")
        if len(raw) > MAX_POINTS:
            raise ChartError(f"линия {s.get('name')!r}: {len(raw)} точек при потолке "
                             f"{MAX_POINTS}, проредь ряд")
        pts = [(_parse_ts(p[0]), p[1]) for p in raw]
        _check_values([v for _, v in pts], f"series[{s.get('name')!r}].points")
        pts.sort(key=lambda p: p[0])
        out.append({**s, "parsed": pts})
    return out, data.get("unit", "")


def _validate_cards(data: dict) -> list[dict]:
    metrics = data.get("metrics") or []
    if len(metrics) < 2:
        raise ChartError(f"метрик {len(metrics)} — карточки нужны от 2 до {MAX_CARDS}")
    if len(metrics) > MAX_CARDS:
        raise ChartError(f"{len(metrics)} метрик при потолке {MAX_CARDS}: "
                         f"больше четырёх крупных чисел с телефона не считываются")
    for m in metrics:
        if not str(m.get("value", "")).strip():
            raise ChartError(f"метрика {m.get('label')!r} без value")
    return metrics


# ── рисование ─────────────────────────────────────────────────────────────────

def _colour(item: dict, idx: int) -> str:
    tone = item.get("tone")
    if tone and tone not in _TONES:
        raise ChartError(f"tone={tone!r}, допустимы {sorted(_TONES)}")
    return _TONES[tone] if tone else _CYCLE[idx % len(_CYCLE)]


def _title_lines(d: ImageDraw.ImageDraw, title: str, width: float):
    """Заголовок обязан помещаться целиком: обрезанный холстом заголовок — сломанная
    картинка. Уменьшаем кегль, потом переносим на две строки, дальше честно падаем."""
    for size in (44, 38, 32):
        f = _font(size, True)
        if d.textlength(title, font=f) <= width:
            return f, [title]
    f = _font(32, True)
    words, lines, cur = title.split(), [], ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if d.textlength(probe, font=f) <= width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > 2 or any(d.textlength(l, font=f) > width for l in lines):
        raise ChartError(
            f"заголовок из {len(title)} символов не помещается даже в две строки — "
            f"сократи его, картинка читается с телефона")
    return f, lines


def _canvas(title: str, fact: str) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    """Возвращает холст и Y, ниже которого можно рисовать: шапка бывает разной высоты."""
    img = Image.new("RGB", (W, H), PALETTE["bg"])
    d = ImageDraw.Draw(img)
    f, lines = _title_lines(d, title, W - 88)
    y = 36
    for line in lines:
        d.text((44, y), line, font=f, fill=PALETTE["ink"])
        y += f.size + 10
    if fact:
        d.text((44, y + 4), fact, font=_font(32), fill=PALETTE["ink_soft"])
        y += 46
    return img, d, y + 8


def _legend(d: ImageDraw.ImageDraw, items: list[tuple[str, str]], y: int) -> None:
    f = _font(28, True)
    x = 44
    for name, colour in items:
        d.rectangle([x, y + 6, x + 34, y + 26], fill=colour)
        d.text((x + 46, y), name, font=f, fill=PALETTE["ink_soft"])
        x += 46 + int(d.textlength(name, font=f)) + 46


def _fit(d: ImageDraw.ImageDraw, text: str, width: float):
    """Крупнейший кегль, при котором подпись влезает в столбец.

    None — если не влезает даже минимальным: на плотных наборах (8 категорий × 3 серии)
    длинное число шире столбца в любом кегле. Тогда подпись не рисуется вовсе: столбец
    показывает форму, число стоит в факт-строке, а налезающие друг на друга цифры не
    читаются ни при каком раскладе.
    """
    for size in (34, 30, 26, 22):
        f = _font(size, True)
        if d.textlength(text, font=f) <= width:
            return f
    return None


def _draw_bars(title: str, cats, series, unit, log: bool) -> Image.Image:
    img, d, y = _canvas(title, _fact_bars(cats, series, unit))
    _legend(d, [(s.get("name", ""), _colour(s, i)) for i, s in enumerate(series)], y)
    top, bot = y + 60, H - PB
    positive = [v for s in series for v in s["values"] if v > 0]
    if log and not positive:
        raise ChartError("все значения нулевые — на логарифмической шкале рисовать нечего")

    if log:
        lo = 10 ** math.floor(math.log10(min(positive)))
        hi = 10 ** math.ceil(math.log10(max(positive)))
        hi = max(hi, lo * 10)
        span = math.log10(hi) - math.log10(lo)
        y_of = lambda v: bot - (math.log10(max(v, lo)) - math.log10(lo)) / span * (bot - top)
    else:
        hi = max(v for s in series for v in s["values"]) or 1
        y_of = lambda v: bot - v / hi * (bot - top)

    band = (W - PL - PR) / len(cats)
    bw = band * 0.76 / len(series)
    f_cat = _font(30)
    for ci, cat in enumerate(cats):
        cx = PL + band * (ci + 0.5)
        for si, s in enumerate(series):
            v = s["values"][ci]
            x0 = cx + (si - len(series) / 2) * bw
            # ноль на лог-шкале рисуем пустотой с явной подписью «0»: полоска у самого низа
            # читалась бы как «мало», а это «ничего»
            y = bot if v == 0 else y_of(v)
            if v > 0:
                d.rectangle([x0 + 4, y, x0 + bw - 4, bot], fill=_colour(s, si))
            lbl = _num(v)
            f = _fit(d, lbl, bw - 6)
            if f is not None:
                d.text((x0 + bw / 2 - d.textlength(lbl, font=f) / 2, y - 44), lbl,
                       font=f, fill=PALETTE["ink"])
        d.text((cx - d.textlength(cat, font=f_cat) / 2, bot + 18), cat,
               font=f_cat, fill=PALETTE["ink_faint"])
    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=3)
    return img          # единицы уже стоят в факт-строке, вторая подпись только мешала


def _find_gaps(pts: list[tuple[dt.datetime, float]]) -> tuple[list[tuple], dt.timedelta]:
    """Порог провала — медианный интервал × 3. Отдавать его наружу значит просить
    вызывающего угадать число, которое видно только из самих данных."""
    deltas = sorted((pts[i][0] - pts[i - 1][0]).total_seconds() for i in range(1, len(pts)))
    median = deltas[len(deltas) // 2] if deltas else 0
    thr = dt.timedelta(seconds=max(median * 3, 1))
    gaps = [(pts[i - 1][0], pts[i][0]) for i in range(1, len(pts))
            if pts[i][0] - pts[i - 1][0] > thr]
    return gaps, thr


def _draw_series(title: str, series: list[dict], unit: str) -> Image.Image:
    first = series[0]["parsed"]
    gaps, thr = _find_gaps(first)
    allt = [t for s in series for t, _ in s["parsed"]]
    t0, t1 = min(allt), max(allt)
    span = (t1 - t0).total_seconds() or 1
    # факт считается по этому срезу, а не по тому, что было в исходном массиве
    img, d, y = _canvas(title, _fact_series(first, gaps, span))

    top, bot = y + 60, H - PB
    vals = [v for s in series for _, v in s["parsed"]]
    vmax = max(vals + [0]) or 1
    vmin = min(vals + [0])
    lo = min(vmin, 0)
    x_of = lambda t: PL + (t - t0).total_seconds() / span * (W - PL - PR)
    y_of = lambda v: bot - (v - lo) / (vmax - lo or 1) * (bot - top)

    for a, b in gaps:
        d.rectangle([x_of(a), top, max(x_of(b), x_of(a) + 2), bot], fill=_GAP_FILL)
    if gaps:
        longest = max(gaps, key=lambda g: g[1] - g[0])
        d.rectangle([x_of(longest[0]), top, x_of(longest[1]), bot], fill=_GAP_FILL_MAX)

    f_tick = _font(30)
    for frac in (0.0, 0.5, 1.0):
        v = lo + (vmax - lo) * frac
        y = y_of(v)
        d.line([(PL, y), (W - PR, y)], fill=PALETTE["border"], width=1)
        d.text((PL + 6, y - 36), f"{_num(v)}{unit}", font=f_tick, fill=PALETTE["ink_faint"])

    items = [(s.get("name", ""), _colour(s, i)) for i, s in enumerate(series)]
    if gaps:
        items.append(("нет данных", _GAP_FILL_MAX))
    _legend(d, items, y)

    for si, s in enumerate(series):
        colour = _colour(s, si)
        seg, prev = [], None
        for t, v in s["parsed"]:
            if prev is not None and t - prev > thr:
                if len(seg) > 1:
                    d.line(seg, fill=colour, width=4, joint="curve")
                seg = []
            seg.append((x_of(t), y_of(v)))
            prev = t
        if len(seg) > 1:
            d.line(seg, fill=colour, width=4, joint="curve")

    step = max(1, round(span / 86400 / 5))
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    while day <= t1:
        lbl = day.strftime("%d.%m")
        d.text((x_of(day) - d.textlength(lbl, font=f_tick) / 2, bot + 18), lbl,
               font=f_tick, fill=PALETTE["ink_faint"])
        day += dt.timedelta(days=step)
    d.line([(PL, bot), (W - PR, bot)], fill=PALETTE["border"], width=3)
    return img


def _draw_cards(title: str, metrics: list[dict]) -> Image.Image:
    img, d, y = _canvas(title, "")        # числа на карточках и есть факты
    f_val, f_lbl, f_note = _font(84, True), _font(28, True), _font(26)
    cw = (W - 88) / len(metrics)
    top = y + 120
    for i, m in enumerate(metrics):
        x = 44 + i * cw
        d.text((x, top), str(m["value"]), font=f_val, fill=_colour(m, i))
        d.text((x, top + 130), str(m.get("label", "")), font=f_lbl, fill=PALETTE["ink_soft"])
        d.text((x, top + 170), str(m.get("note", "")), font=f_note, fill=PALETTE["ink_faint"])
        if i:
            d.line([(x - 24, top - 20), (x - 24, top + 220)], fill=PALETTE["border"], width=1)
    return img


# ── запись ────────────────────────────────────────────────────────────────────

def _save(img: Image.Image) -> str:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = CHART_DIR / f"{stamp}-{uuid.uuid4().hex[:8]}.png"
    img.save(path)
    existing = sorted(CHART_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in existing[_KEEP:]:
        try:
            os.unlink(stale)
        except OSError:
            pass                          # чужой воркер мог удалить раньше — не наше дело
    return str(path)


def render_chart(kind: str, title: str, data: dict) -> str:
    """Нарисовать картинку и вернуть путь к PNG. Ошибки — ChartError с причиной."""
    if kind not in KINDS:
        raise ChartError(f"kind={kind!r}, допустимы {', '.join(KINDS)}")
    if not title or not title.strip():
        raise ChartError("пустой title — картинке нужен заголовок")
    if not isinstance(data, dict):
        raise ChartError(f"data должен быть объектом, пришёл {type(data).__name__}")

    if kind in ("bars", "bars_log"):
        log = kind == "bars_log"
        cats, series, unit = _validate_bars(data, log)
        img = _draw_bars(title.strip(), cats, series, unit, log)
    elif kind == "series":
        series, unit = _validate_series(data)
        img = _draw_series(title.strip(), series, unit)
    else:
        img = _draw_cards(title.strip(), _validate_cards(data))
    return _save(img)
