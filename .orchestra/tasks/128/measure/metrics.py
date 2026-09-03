#!/usr/bin/env python3
"""Метрики замера #128. Одна команда меряет оба плеча одинаково.

Часть метрик снимается рендером (headless Chromium), а не грепом: в #128 греп уже
соврал про шрифты — семья задаётся сокращением `font:`, и `grep font-family` её не видит.

Запуск:  python3 docs/tasks/128/measure/metrics.py <каталог|файл> [...]
"""
import asyncio
import colorsys
import pathlib
import re
import sys

from playwright.async_api import async_playwright

HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
FS_DECL = re.compile(r"font-size\s*:\s*([^;}\n]+)")
# компонентные признаки костяка
COMPONENTS = {
    "tabular": r"tabular-nums",
    "sr-only": r"\.sr-only|aria-label|aria-describedby",
    "badge": r"border-radius\s*:\s*9999px|\.badge",
    "table": r"(?:th|td)[^{]*\{[^}]*border-bottom",
    "focus": r":focus-visible",
    "series": r"--s[1-6]\b|--(?:viz-)?series",
    "print": r"@media\s+print",
}


def accent_hue(css: str) -> tuple[str, float] | None:
    """Тон акцента: первый hex из объявления --accent, иначе самый насыщенный hex."""
    m = re.search(r"--accent\s*:\s*([^;\n]+)", css)
    pool = HEX.findall(m.group(1)) if m else HEX.findall(css)
    best = None
    for h in pool:
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        if 0.12 < light < 0.88 and sat > 0.25 and (best is None or sat > best[2]):
            best = (f"#{h.lower()}", hue * 360, sat)
    return (best[0], best[1]) if best else None


def static_metrics(path: pathlib.Path) -> dict:
    text = path.read_text(errors="replace")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)) or text
    sizes = {v.strip() for v in FS_DECL.findall(css)} - {"inherit", "1em", "inherit;"}
    comps = [k for k, rx in COMPONENTS.items() if re.search(rx, css, re.S | re.I)]
    ext = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]+)', text)
    ext = [u for u in ext if "chart" not in u.lower() and "uplot" not in u.lower()]
    acc = accent_hue(css)
    return {
        "file": path.name,
        "sizes": len(sizes),
        "comp": len(comps),
        "comps": ",".join(sorted(comps)),
        "print": int("print" in comps),
        "offline": int(not ext),
        "accent": acc[0] if acc else "—",
        "hue": round(acc[1]) if acc else -1,
        "purple": int(bool(acc) and 235 <= acc[1] <= 295),
        "bytes": len(text.encode()),
    }


async def rendered(paths: list[pathlib.Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    async with async_playwright() as pw:
        br = await pw.chromium.launch()
        pg = await br.new_page(viewport={"width": 1280, "height": 900})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for p in paths:
            errs.clear()
            await pg.goto("file://" + str(p.resolve()))
            r = await pg.evaluate("""() => {
              const fam = el => el ? getComputedStyle(el).fontFamily.split(',')[0].trim() : '';
              const body = getComputedStyle(document.body);
              const h = document.querySelector('h1,h2,h3');
              const ws = new Set();
              document.querySelectorAll('body *').forEach(e => ws.add(getComputedStyle(e).fontWeight));
              return {bodyFam: fam(document.body), headFam: fam(h), bodyW: body.fontWeight,
                      weights: [...ws].sort().join('/'), height: document.body.scrollHeight};
            }""")
            r["pair"] = int(bool(r["headFam"]) and r["headFam"] != r["bodyFam"])
            r["errors"] = len(errs)
            out[p.name] = r
        await br.close()
    return out


def main() -> None:
    for arg in sys.argv[1:]:
        g = pathlib.Path(arg)
        files = sorted(g.glob("*.html")) if g.is_dir() else [g]
        if not files:
            print(f"### {g}: файлов нет — считать нечего")
            continue
        ren = asyncio.run(rendered(files))
        print(f"\n### {g}  (n={len(files)})")
        print(f"{'файл':26}{'пара':>5}{'кегл':>5}{'комп':>5}{'печ':>4}{'офл':>4}"
              f"{'фиол':>5}{'err':>4}  {'акцент':<9}{'веса':<16}{'семьи'}")
        agg = {"pair": 0, "print": 0, "offline": 0, "purple": 0, "errors": 0}
        sizes, comps = [], []
        for f in files:
            s = static_metrics(f)
            r = ren[f.name]
            agg["pair"] += r["pair"]; agg["print"] += s["print"]
            agg["offline"] += s["offline"]; agg["purple"] += s["purple"]
            agg["errors"] += r["errors"]
            sizes.append(s["sizes"]); comps.append(s["comp"])
            print(f"{f.stem[:25]:26}{r['pair']:>5}{s['sizes']:>5}{s['comp']:>5}"
                  f"{s['print']:>4}{s['offline']:>4}{s['purple']:>5}{r['errors']:>4}  "
                  f"{s['accent']:<9}{r['weights'][:15]:<16}{r['headFam']}/{r['bodyFam']}")
        n = len(files)
        print(f"{'ИТОГО':26}{agg['pair']:>5}{'':5}{'':5}{agg['print']:>4}{agg['offline']:>4}"
              f"{agg['purple']:>5}{agg['errors']:>4}")
        print(f"  пара шрифтов {agg['pair']}/{n} · печать {agg['print']}/{n} · офлайн "
              f"{agg['offline']}/{n} · фиолетовых {agg['purple']}/{n} · ошибок {agg['errors']}")
        print(f"  кеглей на файл: {sorted(sizes)} (медиана {sorted(sizes)[n // 2]})")
        print(f"  компонентов из 7: {sorted(comps)} (медиана {sorted(comps)[n // 2]})")


if __name__ == "__main__":
    main()
