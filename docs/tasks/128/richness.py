#!/usr/bin/env python3
"""#128 — измеряет «насыщенность» дизайна в готовых HTML-артефактах.

Гипотеза оркестратора: скилл #119 переносил ПРИНЦИПЫ («шкала от одной базы»,
«радиусы от одного токена»), и агент исполняет принцип буквально и минимально —
одна база, один радиус, ноль вкуса. Здесь считаются признаки, по которым это видно.

Числа берутся командой, а не глазами. Запуск:
    python3 docs/tasks/128/richness.py docs/tasks/119/measure/before docs/tasks/119/measure/after
"""
import re
import sys
import pathlib

STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
DECL = re.compile(r"([-a-zA-Z]+)\s*:\s*([^;{}]+)")


def css_of(text: str) -> str:
    return "\n".join(STYLE.findall(text))


def decls(css: str, prop: str) -> list[str]:
    return [v.strip() for p, v in DECL.findall(css) if p.lower() == prop]


def numeric_values(vals: list[str]) -> set[str]:
    """Уникальные значения, кроме нулей и наследования."""
    out = set()
    for v in vals:
        v = v.strip().lower()
        if v in ("0", "none", "inherit", "initial", "unset", "0px"):
            continue
        out.add(v)
    return out


def measure(path: pathlib.Path) -> dict:
    text = path.read_text(errors="replace")
    css = css_of(text) or text  # visualize.css приходит как чистый CSS
    tokens = set(re.findall(r"(--[-a-zA-Z0-9]+)\s*:", css))
    fs = numeric_values(decls(css, "font-size"))
    radius = numeric_values(
        decls(css, "border-radius") + decls(css, "border-top-left-radius")
    )
    weights = numeric_values(decls(css, "font-weight"))
    gaps = numeric_values(decls(css, "gap") + decls(css, "row-gap") + decls(css, "column-gap"))
    pads = numeric_values(
        decls(css, "padding") + decls(css, "padding-block") + decls(css, "padding-inline")
    )
    shadows = [v for v in decls(css, "box-shadow") if v.strip().lower() != "none"]
    focus_shadows = [v for v in shadows if "inset" in v and "ring" in v]
    hexes = set(h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", css))
    return {
        "file": f"{path.parent.name}/{path.name}",
        "bytes": len(text.encode()),
        "css_bytes": len(css.encode()),
        "tokens": len(tokens),
        "font_sizes": len(fs),
        "font_weights": len(weights),
        "radii": len(radius),
        "gaps": len(gaps),
        "paddings": len(pads),
        "shadows": len(shadows),
        "focus_rings": len(focus_shadows),
        "color_mix": len(re.findall(r"color-mix\(", css)),
        "light_dark": len(re.findall(r"light-dark\(", css)),
        "focus_visible": len(re.findall(r":focus-visible", css)),
        "transitions": len(decls(css, "transition")),
        "hex_colors": len(hexes),
        "series_tokens": len(
            [t for t in tokens if re.search(r"series|chart|cat-?\d|viz-\d", t)]
        ),
        "tabular_nums": len(re.findall(r"tabular-nums", css)),
        "sr_only": len(re.findall(r"\.sr-only", css)),
        "media_blocks": len(re.findall(r"@media", css)),
        "svg": len(re.findall(r"<svg", text)),
    }


COLS = [
    "tokens", "font_sizes", "font_weights", "radii", "gaps", "paddings",
    "shadows", "focus_visible", "color_mix", "light_dark", "transitions",
    "hex_colors", "series_tokens", "tabular_nums", "sr_only", "media_blocks",
    "css_bytes",
]


def main() -> None:
    groups = [pathlib.Path(a) for a in sys.argv[1:]]
    for g in groups:
        files = sorted(g.glob("*.html")) if g.is_dir() else [g]
        rows = [measure(f) for f in files]
        print(f"\n### {g}  (n={len(rows)})")
        head = f"{'file':28}" + "".join(f"{c[:9]:>10}" for c in COLS)
        print(head)
        for r in rows:
            print(f"{r['file'][:27]:28}" + "".join(f"{r[c]:>10}" for c in COLS))
        if len(rows) > 1:
            med = {c: sorted(r[c] for r in rows)[len(rows) // 2] for c in COLS}
            print(f"{'МЕДИАНА':28}" + "".join(f"{med[c]:>10}" for c in COLS))


if __name__ == "__main__":
    main()
