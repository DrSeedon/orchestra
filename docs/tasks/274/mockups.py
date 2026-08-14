"""#274 фаза 1: три макета картинки /limits в HTML → PNG.

Запуск: `.venv/bin/python docs/tasks/274/mockups.py` из корня worktree.
Данные — замороженный снимок `sample-usage.json` (живой `/api/usage` от 14.08 08:00 UTC),
чтобы макеты пересобирались одинаково и числа в них можно было проверить руками.

Все производные числа считает ЭТОТ код по тем данным, что реально нарисованы, — правило
`app/charts.py`. Курс «сколько недельного стоит одно пятичасовое окно» берётся из
`quota_headroom.rate` (`app/routes/system.py:897`), второй арифметики здесь нет.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOW = dt.datetime(2026, 8, 14, 8, 0, 45, tzinfo=dt.timezone.utc)
LOCAL = dt.timezone(dt.timedelta(hours=7))

P = {
    "bg": "#0a0e17", "panel": "#111827", "border": "#334155",
    "ink": "#e2e8f0", "soft": "#a6b3c6", "faint": "#8595ab",
    "accent": "#818cf8", "alt": "#38bdf8",
    "ok": "#22c55e", "warn": "#eab308", "danger": "#ef4444",
}


def _reset_text(iso: str | None) -> str:
    if not iso:
        return "сброс не указан"
    when = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    left = (when - NOW).total_seconds()
    if left <= 0:
        return "обнулится с минуты на минуту"
    days, rem = divmod(int(left // 60), 24 * 60)
    hours, minutes = divmod(rem, 60)
    if days:
        rel = f"через {days} дн {hours} ч"
    elif hours:
        rel = f"через {hours} ч {minutes} мин"
    else:
        rel = f"через {minutes} мин"
    return f"{rel} · {when.astimezone(LOCAL).strftime('%d.%m в %H:%M')}"


def collect(usage: dict) -> dict:
    """Снимок → плоские числа для рисования. Пул без данных остаётся с used=None."""
    anthropic = usage.get("anthropic") or {}
    codex = usage.get("codex") or {}
    grok = usage.get("grok") or {}
    head = usage.get("quota_headroom") or {}

    def pool(name: str, window: dict | None) -> dict:
        window = window if isinstance(window, dict) else {}
        used = window.get("utilization")
        used = float(used) if isinstance(used, (int, float)) else None
        return {"name": name, "used": used, "reset": _reset_text(window.get("resets_at"))}

    pools = [
        pool("Claude · 5 часов", anthropic.get("five_hour")),
        pool("Claude · неделя", anthropic.get("seven_day")),
        pool("Codex", codex.get("primary")),
        pool("Spark", (codex.get("spark") or {}).get("primary")),
        pool("Grok", grok.get("primary")),
    ]

    rate = head.get("rate")  # сколько процентов недели стоит 1 % пятичасового окна
    five_used = pools[0]["used"] or 0.0
    week_used = pools[1]["used"] or 0.0
    cost = rate * 100 if isinstance(rate, (int, float)) and rate > 0 else None
    return {
        "pools": pools,
        "five_used": five_used,
        "week_used": week_used,
        "cost": cost,                                    # % недели за одно полное окно
        "total": (100 / cost) if cost else None,         # сколько окон влезает в неделю
        "spent": (week_used / cost) if cost else None,   # сколько окон уже сожжено
        "left": (100 - week_used) / cost if cost else None,
        "visible_pct": max(0.0, 100 - five_used),        # свободно на шкале 5 часов
        "available_pct": head.get("available_pct"),      # сколько из них реально возьмёшь
        "locked_pct": head.get("locked_pct"),
        "window_hours": head.get("window_hours"),
    }


# ── общие куски вёрстки ───────────────────────────────────────────────────────

CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:1000px; background:{P['bg']}; color:{P['ink']};
  font-family:'DejaVu Sans',system-ui,sans-serif; padding:46px 46px 40px; }}
.head {{ font-size:30px; color:{P['faint']}; letter-spacing:.5px; }}
.huge {{ font-size:84px; font-weight:700; line-height:1.06; }}
.sub {{ font-size:38px; color:{P['soft']}; margin-top:10px; line-height:1.35; }}
.note {{ font-size:29px; color:{P['faint']}; margin-top:26px; line-height:1.45; }}
.pools {{ margin-top:38px; border-top:2px solid {P['border']}; padding-top:26px;
  display:flex; flex-direction:column; gap:19px; }}
.pool {{ display:flex; align-items:center; gap:16px; font-size:26px; }}
.pool .nm {{ width:225px; color:{P['soft']}; white-space:nowrap; }}
.pool .tr {{ flex:1 1 0; min-width:0; height:24px; background:#1b2436;
  border-radius:12px; overflow:hidden; }}
.pool .fl {{ height:100%; border-radius:12px; }}
.pool .vl {{ width:180px; text-align:right; font-weight:700; white-space:nowrap; }}
.pool .rs {{ width:375px; font-size:22px; color:{P['faint']}; text-align:right;
  white-space:nowrap; }}
.nodata {{ flex:1; color:{P['faint']}; font-style:italic; }}
"""


def bar_color(used: float) -> str:
    return P["danger"] if used >= 85 else P["warn"] if used >= 60 else P["ok"]


def pools_html(pools: list[dict]) -> str:
    rows = []
    for p in pools:
        if p["used"] is None:
            rows.append(
                f'<div class="pool"><div class="nm">{p["name"]}</div>'
                f'<div class="nodata">нет данных — сервис не ответил</div></div>'
            )
            continue
        used = p["used"]
        rows.append(
            f'<div class="pool"><div class="nm">{p["name"]}</div>'
            f'<div class="tr"><div class="fl" style="width:{used:.1f}%;'
            f'background:{bar_color(used)}"></div></div>'
            f'<div class="vl">занято {used:.0f}%</div>'
            f'<div class="rs">{p["reset"]}</div></div>'
        )
    return f'<div class="pools">{"".join(rows)}</div>'


def page(body: str, extra_css: str = "") -> str:
    return (f"<!doctype html><meta charset='utf-8'><style>{CSS}{extra_css}</style>"
            f"<body>{body}</body>")


# ── вариант A: сетка пятичасовых окон ─────────────────────────────────────────

def variant_a(d: dict) -> str:
    css = f"""
.grid {{ display:flex; gap:12px; margin-top:34px; }}
.cell {{ flex:1; height:132px; border-radius:14px; background:#161f31;
  border:2px solid {P['border']}; position:relative; overflow:hidden; }}
.cell .burn {{ position:absolute; left:0; bottom:0; width:100%;
  background:{P['danger']}; opacity:.85; }}
.cell .free {{ position:absolute; left:0; bottom:0; width:100%;
  background:{P['ok']}; opacity:.30; }}
.cell.dead {{ border-style:dashed; border-color:#3a4560; background:
  repeating-linear-gradient(135deg,#131a29 0 10px,#0e1522 10px 20px); }}
.cell .cap {{ position:absolute; left:0; right:0; bottom:8px; text-align:center;
  font-size:22px; color:{P['faint']}; }}
.legend {{ display:flex; gap:34px; margin-top:22px; font-size:26px; color:{P['soft']}; }}
.legend i {{ display:inline-block; width:26px; height:26px; border-radius:6px;
  vertical-align:-4px; margin-right:10px; }}
"""
    total, spent, left = d["total"], d["spent"], d["left"]
    cells = []
    for k in range(1, int(total // 1) + 2):
        burn = min(1.0, max(0.0, spent - (k - 1)))
        cap = min(1.0, max(0.0, total - (k - 1)))
        free = max(0.0, cap - burn)
        if cap <= 0.01:
            cells.append(f'<div class="cell dead"><div class="cap">не влезает</div></div>')
            continue
        cells.append(
            f'<div class="cell">'
            f'<div class="free" style="height:{(burn + free) * 100:.0f}%"></div>'
            f'<div class="burn" style="height:{burn * 100:.0f}%"></div>'
            f'<div class="cap">{k}</div></div>'
        )
    body = (
        f'<div class="head">ЛИМИТЫ · {NOW.astimezone(LOCAL).strftime("%d.%m %H:%M")}</div>'
        f'<div class="huge">Осталось <span style="color:{P["warn"]}">{left:.1f}</span> '
        f'окна</div>'
        f'<div class="sub">Неделя вмещает {total:.1f} полных пятичасовых окна, '
        f'{spent:.1f} уже сожжено.</div>'
        f'<div class="grid">{"".join(cells)}</div>'
        f'<div class="legend">'
        f'<span><i style="background:{P["danger"]}"></i>сожжено</span>'
        f'<span><i style="background:{P["ok"]};opacity:.4"></i>ещё можно взять</span>'
        f'<span><i style="background:#131a29;border:2px solid #3a4560"></i>'
        f'недели не хватит</span></div>'
        f'<div class="note">Шкала «ближайшие 5 часов» показывает {d["visible_pct"]:.0f}% '
        f'свободных, но взять из них можно только {d["available_pct"]:.0f}% — '
        f'остальное упирается в недельный запас.</div>'
        f'{pools_html(d["pools"])}'
    )
    return page(body, css)


# ── вариант B: вложенная шкала ────────────────────────────────────────────────

def variant_b(d: dict) -> str:
    css = f"""
.week {{ margin-top:36px; height:108px; border-radius:16px; background:#161f31;
  border:2px solid {P['border']}; position:relative; overflow:hidden; }}
.week .burn {{ position:absolute; inset:0 auto 0 0; background:{P['danger']}; opacity:.85; }}
.week .tick {{ position:absolute; top:0; bottom:0; width:2px; background:#0a0e17; opacity:.55; }}
.week .lbl {{ position:absolute; top:34px; font-size:30px; font-weight:700; color:#fff;
  text-shadow:0 2px 6px #000; }}
.axis {{ display:flex; justify-content:space-between; margin-top:12px;
  font-size:25px; color:{P['faint']}; }}
.five {{ margin-top:40px; height:88px; border-radius:16px; background:#161f31;
  border:2px solid {P['border']}; position:relative; overflow:hidden; }}
.five .burn {{ position:absolute; inset:0 auto 0 0; background:{P['danger']}; opacity:.85; }}
.five .avail {{ position:absolute; top:0; bottom:0; background:{P['ok']}; opacity:.32; }}
.five .locked {{ position:absolute; top:0; bottom:0; background:
  repeating-linear-gradient(135deg,#2b3448 0 10px,#1b2233 10px 20px); }}
.cap {{ font-size:29px; color:{P['soft']}; margin-top:14px; }}
"""
    total, spent, left = d["total"], d["spent"], d["left"]
    ticks = "".join(
        f'<div class="tick" style="left:{k / total * 100:.2f}%"></div>'
        for k in range(1, int(total) + 1)
    )
    five_used, avail, locked = d["five_used"], d["available_pct"], d["locked_pct"]
    body = (
        f'<div class="head">ЛИМИТЫ · {NOW.astimezone(LOCAL).strftime("%d.%m %H:%M")}</div>'
        f'<div class="huge">Недели хватит на <span style="color:{P["warn"]}">'
        f'{left:.1f}</span> окна</div>'
        f'<div class="cap">Полоса ниже — вся неделя. Насечки делят её на пятичасовые '
        f'окна: их помещается {total:.1f}.</div>'
        f'<div class="week"><div class="burn" style="width:{d["week_used"]:.1f}%"></div>'
        f'{ticks}<div class="lbl" style="left:24px">сожжено {spent:.1f} окна</div></div>'
        f'<div class="axis"><span>вся неделя = {total:.1f} окна</span>'
        f'<span style="color:{P["ok"]}">осталось {left:.1f} · '
        f'обнулится {d["pools"][1]["reset"].split("·")[-1].strip()}</span></div>'
        f'<div class="cap" style="margin-top:38px">А это ближайшие 5 часов. Зелёное — '
        f'сколько на самом деле можно взять, полосатое — то, что недельный запас уже '
        f'не пустит.</div>'
        f'<div class="five"><div class="burn" style="width:{five_used:.1f}%"></div>'
        f'<div class="avail" style="left:{five_used:.1f}%;width:{avail:.1f}%"></div>'
        f'<div class="locked" style="left:{five_used + avail:.1f}%;width:{locked:.1f}%"></div>'
        f'</div>'
        f'<div class="axis"><span>сожжено {five_used:.0f}%</span>'
        f'<span>доступно {avail:.0f}%</span>'
        f'<span>заперто неделей {locked:.0f}%</span></div>'
        f'{pools_html(d["pools"])}'
    )
    return page(body, css)


# ── вариант C: карточки ───────────────────────────────────────────────────────

def variant_c(d: dict) -> str:
    css = f"""
.cards {{ display:flex; gap:20px; margin-top:34px; }}
.card {{ flex:1; background:{P['panel']}; border:2px solid {P['border']};
  border-radius:20px; padding:28px 26px 26px; }}
.card .k {{ font-size:26px; color:{P['faint']}; text-transform:uppercase;
  letter-spacing:1px; }}
.card .v {{ font-size:86px; font-weight:700; line-height:1.05; margin-top:8px; }}
.card .u {{ font-size:27px; color:{P['soft']}; margin-top:8px; line-height:1.35; }}
.strip {{ margin-top:30px; background:{P['panel']}; border:2px solid {P['border']};
  border-radius:20px; padding:26px 28px; font-size:30px; color:{P['soft']};
  line-height:1.45; }}
.strip b {{ color:{P['ink']}; }}
"""
    body = (
        f'<div class="head">ЛИМИТЫ · {NOW.astimezone(LOCAL).strftime("%d.%m %H:%M")}</div>'
        f'<div class="huge" style="font-size:74px">Сколько ещё можно работать</div>'
        f'<div class="cards">'
        f'<div class="card"><div class="k">осталось на неделе</div>'
        f'<div class="v" style="color:{P["warn"]}">{d["left"]:.1f}</div>'
        f'<div class="u">полных пятичасовых окна из {d["total"]:.1f}</div></div>'
        f'<div class="card"><div class="k">одно окно стоит</div>'
        f'<div class="v" style="color:{P["alt"]}">{d["cost"]:.0f}%</div>'
        f'<div class="u">недельного запаса, по расходу за {d["window_hours"]} ч</div></div>'
        f'<div class="card"><div class="k">прямо сейчас доступно</div>'
        f'<div class="v" style="color:{P["ok"]}">{d["available_pct"]:.0f}%</div>'
        f'<div class="u">пятичасового окна, хотя пустым оно выглядит на '
        f'{d["visible_pct"]:.0f}%</div></div>'
        f'</div>'
        f'<div class="strip">Пятичасовое окно почти пустое, но это не значит, что можно '
        f'работать в полную силу: <b>недельный запас пустит только {d["left"]:.1f} '
        f'окна</b>, и он обнулится {d["pools"][1]["reset"]}.</div>'
        f'{pools_html(d["pools"])}'
    )
    return page(body, css)


def main() -> None:
    usage = json.loads((HERE / "sample-usage.json").read_text())
    d = collect(usage)
    print(f"курс: одно 5h-окно = {d['cost']:.2f}% недели (замер за {d['window_hours']} ч)")
    print(f"в неделю влезает {d['total']:.2f} окна; сожжено {d['spent']:.2f}; "
          f"осталось {d['left']:.2f}")
    print(f"5h выглядит свободным на {d['visible_pct']:.0f}%, доступно {d['available_pct']}%, "
          f"заперто {d['locked_pct']}%")

    variants = {"a-grid": variant_a(d), "b-nested": variant_b(d), "c-cards": variant_c(d)}
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page_ = browser.new_page(viewport={"width": 1000, "height": 900})
        errors: list[str] = []
        page_.on("pageerror", lambda e: errors.append(str(e)))
        for name, html in variants.items():
            (HERE / f"{name}.html").write_text(html)
            page_.goto((HERE / f"{name}.html").as_uri())
            png = HERE / f"{name}.png"
            page_.screenshot(path=str(png), full_page=True)
            box = page_.evaluate("() => [document.body.scrollWidth, document.body.scrollHeight]")
            print(f"{name}: {png.name} {box[0]}x{box[1]} {png.stat().st_size // 1024} КБ")
        browser.close()
        if errors:
            raise SystemExit(f"ошибки страницы: {errors}")


if __name__ == "__main__":
    main()
