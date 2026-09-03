#!/usr/bin/env python3
"""M1-M5 по каталогу с .html-артефактами (#119).

Считает наблюдаемые признаки, а не мнение. Печатает таблицу и сырые числа.
Выход != 0, если каталог пуст или провален M5 (регресс-гард).

    python3 metrics.py <dir> [<dir> ...]
"""
import colorsys
import re
import sys
from pathlib import Path

# Единственный CDN, разрешённый нашим скиллом (графики). Всё остальное = не офлайн.
ALLOWED_CDN = re.compile(r"cdn\.jsdelivr\.net/npm/(chart\.js|uplot)")
EXTERNAL_REF = re.compile(
    r"""<(?:script[^>]*\ssrc|link[^>]*\shref)\s*=\s*["'](https?:)?//([^"']+)["']""",
    re.I,
)
HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
RGB = re.compile(r"rgb\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)", re.I)
FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}\n]+)", re.I)
INTERACTIVE = re.compile(r"<(?:button|input|select|textarea)\b|<details\b", re.I)

# Полоса «фиолетового/фиолетово-синего», который gpt-5.5 запрещает дословно.
# Границы выведены из замера, а не round number: indigo-500 = 238.7, violet-500 = 258.3,
# fuchsia-500 = 292.2, при этом blue-500 = 217.2 остаётся снаружи с запасом 18°.
# Изначально стояло 260-290 — и пропускало violet-500 (#8b5cf6), самый ходовой AI-дефолт.
PURPLE_BAND = (235, 295)


def to_hsl(rgb):
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100, l * 100


def colors(text):
    out = [tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) for m in HEX.finditer(text)]
    out += [(int(m.group(1)), int(m.group(2)), int(m.group(3))) for m in RGB.finditer(text)]
    return out


ACCENT_TOKEN = re.compile(
    r"--(?:accent|primary|brand)[a-z0-9-]*\s*:\s*([^;\n}]+)", re.I
)


def declared_accent(text):
    """Акцент, ОБЪЯВЛЕННЫЙ артефактом в токене (--accent/--primary/--brand).

    Это и есть выбранная айдентика. Считать «самый частый насыщенный цвет» нельзя:
    в пилоте #119 два артефакта с ОДНИМ И ТЕМ ЖЕ `--accent: #7c3aed` дали разные
    «доминирующие» цвета просто потому, что в одном 12 раз повторился красный статус
    инцидента, а в другом красный/зелёный/фиолетовый встретились по разу и победил
    тайбрейк. Метрика мерила частоту статусных цветов, а не палитру артефакта,
    и показывала разнообразие там, где артефакты идентичны.
    """
    for raw in ACCENT_TOKEN.findall(text):
        for rgb in colors(raw):
            h, s, light = to_hsl(rgb)
            if s >= 15 and 8 < light < 95:
                return "#%02x%02x%02x" % rgb, h
    return None, None


def dominant_accent(text):
    """Запасной путь: самый частый насыщенный цвет, если токен не объявлен.

    Серые/чёрные/белые отбрасываются: они есть в любой теме и акцент не характеризуют.
    """
    counts = {}
    for rgb in colors(text):
        h, s, light = to_hsl(rgb)
        if s < 25 or light < 12 or light > 92:
            continue
        counts[rgb] = counts.get(rgb, 0) + 1
    if not counts:
        return None, None
    best = max(counts, key=lambda c: (counts[c], -to_hsl(c)[2]))
    return "#%02x%02x%02x" % best, to_hsl(best)[0]


def analyse(path):
    t = path.read_text(encoding="utf-8", errors="replace")
    accent, hue = declared_accent(t)
    inferred = accent is None
    if inferred:
        accent, hue = dominant_accent(t)

    sizes = {s.strip() for s in FONT_SIZE.findall(t)}
    derived = any(("var(" in s or "calc(" in s) for s in sizes)
    headings = len({h for h in re.findall(r"<h([1-6])\b", t, re.I)})
    hierarchy = len(sizes) >= 3 and (derived or headings >= 3)

    interactive = bool(INTERACTIVE.search(t))
    focus = ":focus-visible" in t

    ext = [u for _, u in EXTERNAL_REF.findall(t) if not ALLOWED_CDN.search(u)]
    offline = not ext
    printable = "@media print" in t.replace("@media  print", "@media print")
    single = "<html" in t.lower()

    return {
        "file": path.name,
        "bytes": len(t.encode()),
        "accent": (accent or "—") + ("~" if inferred and accent else ""),
        "inferred": inferred,
        "hue": round(hue) if hue is not None else None,
        "purple": hue is not None and PURPLE_BAND[0] <= hue <= PURPLE_BAND[1],
        "sizes": len(sizes),
        "derived": derived,
        "headings": headings,
        "M3": hierarchy,
        "interactive": interactive,
        "M4": focus if interactive else None,
        "offline": offline,
        "external": ext,
        "print": printable,
        "single": single,
        # M5 = регресс-гард: только то, что нынешний скилл УЖЕ обещает (один файл + офлайн).
        # `@media print` в проектный скилл не входит вовсе (он есть лишь в глобальном),
        # поэтому baseline валит его 5/5 — как блокер это остановило бы всё и не защитило
        # бы ничего. Печать вынесена в M6: это прирост, а не регресс.
        "M5": offline and single,
        "M6": printable,
        "has_7c3aed": "7c3aed" in t.lower(),
    }


def report(d):
    files = sorted(Path(d).glob("*.html"))
    if not files:
        print(f"!! {d}: ни одного .html — считать нечего", file=sys.stderr)
        return None
    rows = [analyse(f) for f in files]

    print(f"\n=== {d} ({len(rows)} артефактов) ===")
    head = (f"{'файл':30} {'акцент':9} {'hue':>4} {'кегли':>5} {'загл':>4} "
            f"{'M3':>4} {'M4':>4} {'M5':>4} {'M6':>4}")
    print(head)
    print("-" * len(head))
    for r in rows:
        m4 = "—" if r["M4"] is None else ("ok" if r["M4"] else "FAIL")
        # hue=0 (красный) — валидное значение; `or '—'` съедал его как falsy.
        hue = "—" if r["hue"] is None else str(r["hue"])
        print(
            f"{r['file'][:30]:30} {r['accent']:9} {hue:>4} "
            f"{r['sizes']:>5} {r['headings']:>4} {'ok' if r['M3'] else 'FAIL':>4} "
            f"{m4:>4} {'ok' if r['M5'] else 'FAIL':>4} {'ok' if r['M6'] else '—':>4}"
        )

    accents = [r["accent"] for r in rows if r["accent"] != "—"]
    uniq = sorted(set(accents))
    m2 = sum(1 for r in rows if r["purple"])
    m3 = sum(1 for r in rows if r["M3"])
    m4_app = [r for r in rows if r["M4"] is not None]
    m4 = sum(1 for r in m4_app if r["M4"])
    m5 = sum(1 for r in rows if r["M5"])
    m6 = sum(1 for r in rows if r["M6"])
    inf = sum(1 for r in rows if r["inferred"])
    print(
        f"\nM1 уникальных акцентов : {len(uniq)} из {len(rows)}  {uniq}"
        f"\nM2 фиолетовых (H235-295): {m2} из {len(rows)}"
        f"\nM3 иерархия            : {m3} из {len(rows)}"
        f"\nM4 focus-visible       : {m4} из {len(m4_app)} интерактивных"
        f"\nM5 офлайн + один файл  : {m5} из {len(rows)}   <- БЛОКЕР"
        f"\nM6 @media print        : {m6} из {len(rows)}   (прирост, не блокер)"
    )
    if inf:
        print(f"акцент выведен по частоте (нет токена), помечен ~: {inf} из {len(rows)}")
    leak = [r["file"] for r in rows if r["has_7c3aed"]]
    if leak:
        print(f"следы старого #7c3aed  : {leak}")
    for r in rows:
        if r["external"]:
            print(f"внешние ссылки в {r['file']}: {r['external']}")
    return {"n": len(rows), "m1": len(uniq), "m2": m2, "m3": m3,
            "m4": (m4, len(m4_app)), "m5": m5, "accents": accents}


if __name__ == "__main__":
    dirs = sys.argv[1:] or ["before", "after"]
    results = [report(d) for d in dirs]
    if any(r is None for r in results):
        sys.exit(2)
    if any(r["m5"] != r["n"] for r in results):
        print("\nM5 ПРОВАЛЕН — блокер, независимо от остальных метрик", file=sys.stderr)
        sys.exit(1)
    print("\nM5 пройден во всех каталогах")
