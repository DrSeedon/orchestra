"""Картинка `/limits`: вложенная шкала недели и пятичасового окна, HTML → PNG.

Почему HTML, а не Pillow как в `app/charts.py`: здесь не график, а вёрстка — вложенные
полосы, насечки, двухстрочные строки пулов. Руками по пикселям это не поддерживается.

Оконная арифметика (сколько окна прошло и обгоняет ли расход календарь) живёт тоже здесь и
используется И картинкой, И текстом под ней (`_format_limits_message_for_chat`), чтобы
цифры в подписи и на картинке не разъезжались.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

# Порог темпа зеркалит фронтовый `_paceIndicator` (app/static/js/usage.js:46):
# отставание в 5 п.п. от календаря считается нормой, дальше — обгон.
PACE_OK_DELTA = 5.0
PACE_WARN_DELTA = 20.0
WINDOW_FALLBACK_MINUTES = {"five_hour": 300, "seven_day": 10080}

LOCAL_TZ = dt.timezone(dt.timedelta(hours=7))
RENDER_TIMEOUT_MS = 20_000
CARD_WIDTH = 900

P = {
    "bg": "#0a0e17", "panel": "#111827", "border": "#334155",
    "ink": "#e2e8f0", "soft": "#a6b3c6", "faint": "#8595ab",
    "accent": "#818cf8", "alt": "#38bdf8",
    "ok": "#22c55e", "warn": "#eab308", "danger": "#ef4444",
}


# ── оконная арифметика (общая с текстом под картинкой) ────────────────────────

def resolve_window_minutes(window_id: str | None, window: dict) -> int | None:
    window_minutes = window.get("window_minutes")
    if isinstance(window_minutes, int) and window_minutes > 0:
        return window_minutes
    return WINDOW_FALLBACK_MINUTES.get(window_id) if window_id else None


def progress_pct(reset: dt.datetime, window_minutes: int | None,
                 now: dt.datetime) -> int | None:
    """Сколько процентов окна прошло. None — длительность окна неизвестна."""
    if not isinstance(window_minutes, int) or window_minutes <= 0:
        return None
    remaining = (reset - now).total_seconds()
    elapsed = window_minutes * 60 - remaining
    return int(max(0, min(100, round(elapsed / (window_minutes * 60) * 100))))


def pace_delta(utilization: float, reset: dt.datetime, window_minutes: int | None,
               now: dt.datetime) -> float | None:
    """Расход минус пройденная часть окна, в п.п. Плюс = обгоняем календарь."""
    if not isinstance(window_minutes, int) or window_minutes <= 0:
        return None
    remain_ms = max(0, int((reset - now).total_seconds() * 1000))
    elapsed_ms = window_minutes * 60_000 - remain_ms
    return utilization - (elapsed_ms / (window_minutes * 60_000)) * 100


def pace_text(utilization: float, reset: dt.datetime, window_minutes: int | None,
              now: dt.datetime) -> str:
    """Формулировка темпа для ТЕКСТА под картинкой. Формат не менять — он в тестах #273."""
    delta = pace_delta(utilization, reset, window_minutes, now)
    if delta is None:
        return "темп не известен"
    if delta <= PACE_OK_DELTA:
        return "темп ok"
    cooldown_min = round(delta * (window_minutes * 60_000) / 100 / 60_000)
    if cooldown_min < 60:
        label = f"{cooldown_min}m"
    elif cooldown_min < 1440:
        label = f"{cooldown_min // 60}ч {cooldown_min % 60}м"
    else:
        days, rest = divmod(cooldown_min, 1440)
        label = f"{days}д {rest // 60}ч {rest % 60}м"
    return f"темп +{label}"


def pace_badge(delta: float | None) -> tuple[str, str]:
    """Темп человеческими словами и цвет для КАРТИНКИ. Цвет кодирует ровно одно:
    обгоняет ли расход календарь. По абсолютному проценту не красим — 90% за 95% окна
    это норма, а 30% за 5% окна беда."""
    if delta is None:
        return "темп — нет данных", P["faint"]
    if delta <= PACE_OK_DELTA:
        return "в графике", P["ok"]
    return f"обгон +{delta:.0f} п.п.", P["warn" if delta <= PACE_WARN_DELTA else "danger"]


def to_utc(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _countdown(reset: dt.datetime, now: dt.datetime) -> str:
    seconds = int((reset - now).total_seconds())
    if seconds <= 0:
        return "обнулится с минуты на минуту"
    minutes_total = max(1, (seconds + 59) // 60)
    days, minutes_total = divmod(minutes_total, 24 * 60)
    hours, minutes = divmod(minutes_total, 60)
    if days:
        rel = f"{days} дн {hours} ч"
    elif hours:
        rel = f"{hours} ч {minutes} мин"
    else:
        rel = f"{minutes} мин"
    return f"обнулится через {rel} · {reset.astimezone(LOCAL_TZ).strftime('%d.%m %H:%M')}"


# ── сбор данных ───────────────────────────────────────────────────────────────

def collect(usage: dict, *, now: dt.datetime | None = None) -> dict:
    """Ответ `/api/usage` → всё, что рисует карточка."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)

    anthropic = usage.get("anthropic") or {}
    codex = usage.get("codex") or {}

    def pool(label: str, window: dict | None, window_id: str | None = None) -> dict:
        window = window if isinstance(window, dict) else {}
        used = window.get("utilization")
        if not isinstance(used, (int, float)):
            # Форма ответа одна на обе ветки: словарь с разным набором ключей — мина
            # для рисовалки, она обходит пулы одним циклом.
            return {"label": label, "used": None, "elapsed": None,
                    "pace": None, "color": None, "reset": None}
        used = float(used)
        reset = to_utc(window.get("resets_at"))
        minutes = resolve_window_minutes(window_id, window)
        elapsed = progress_pct(reset, minutes, now) if reset else None
        delta = pace_delta(used, reset, minutes, now) if reset else None
        badge, color = pace_badge(delta)
        return {
            "label": label, "used": used, "elapsed": elapsed,
            "pace": badge, "color": color,
            "reset": _countdown(reset, now) if reset else "сброс не указан",
        }

    pools = [
        pool("Claude · 5 часов", anthropic.get("five_hour"), "five_hour"),
        pool("Claude · неделя", anthropic.get("seven_day"), "seven_day"),
        pool("Codex", codex.get("primary")),
        pool("Spark", (codex.get("spark") or {}).get("primary")),
        pool("Grok", (usage.get("grok") or {}).get("primary")),
    ]

    return {"now": now, "pools": pools}


# ── вёрстка ───────────────────────────────────────────────────────────────────

def _css() -> str:
    return f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{CARD_WIDTH}px; background:{P['bg']}; color:{P['ink']}; padding:40px 40px 34px;
  font-family:'DejaVu Sans','Noto Sans',system-ui,sans-serif; }}
.head {{ font-size:30px; color:{P['faint']}; letter-spacing:1px; }}
.pools {{ margin-top:36px; border-top:2px solid {P['border']}; padding-top:26px;
  display:flex; flex-direction:column; gap:24px; }}
.pool .top {{ display:flex; justify-content:space-between; align-items:baseline;
  font-size:31px; gap:16px; }}
.pool .nm {{ color:{P['ink']}; }}
.pool .vl {{ font-weight:700; white-space:nowrap; }}
.pool .dim {{ color:{P['faint']}; font-weight:400; font-size:28px; }}
.pool .tr {{ margin-top:9px; height:20px; background:#1b2436; border-radius:10px;
  position:relative; overflow:hidden; }}
.pool .fl {{ position:absolute; inset:0 auto 0 0; border-radius:10px; }}
.pool .mark {{ position:absolute; top:-4px; bottom:-4px; width:4px; background:{P['ink']};
  opacity:.9; }}
.pool .bot {{ display:flex; justify-content:space-between; margin-top:9px; font-size:29px;
  gap:16px; white-space:nowrap; }}
.pool .rs {{ color:{P['faint']}; }}
.pool .nm, .pool .vl {{ white-space:nowrap; }}
.nodata {{ font-size:29px; color:{P['faint']}; font-style:italic; margin-top:6px; }}
"""


def _pools_html(pools: list[dict]) -> str:
    rows = []
    for p in pools:
        name = html.escape(p["label"])
        if p["used"] is None:
            rows.append(
                f'<div class="pool"><div class="top"><span class="nm">{name}</span></div>'
                f'<div class="nodata">нет данных — сервис не ответил</div></div>'
            )
            continue
        used, elapsed = p["used"], p["elapsed"]
        window_note = (f' <span class="dim">(окно прошло {elapsed}%)</span>'
                       if elapsed is not None else ' <span class="dim">(окно неизвестно)</span>')
        mark = (f'<div class="mark" style="left:{min(99.5, max(0.0, float(elapsed))):.1f}%"></div>'
                if elapsed is not None else '')
        rows.append(
            f'<div class="pool">'
            f'<div class="top"><span class="nm">{name}</span>'
            f'<span class="vl">занято {used:.0f}%{window_note}</span></div>'
            f'<div class="tr"><div class="fl" style="width:{max(0.0, min(100.0, used)):.1f}%;'
            f'background:{p["color"]}"></div>{mark}</div>'
            f'<div class="bot"><span style="color:{p["color"]}">{html.escape(p["pace"])}</span>'
            f'<span class="rs">{html.escape(p["reset"])}</span></div></div>'
        )
    return f'<div class="pools">{"".join(rows)}</div>'


def build_html(data: dict) -> str:
    stamp = data["now"].astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")
    return (
        f"<!doctype html><meta charset='utf-8'><style>{_css()}</style><body>"
        f'<div class="head">ЛИМИТЫ · {stamp}</div>{_pools_html(data["pools"])}'
        f"</body>"
    )


async def render_limits_card(usage: dict, *, now: dt.datetime | None = None) -> str:
    """HTML → PNG. Путь к файлу. Кидает наружу — вызывающий откатывается на текст."""
    from playwright.async_api import async_playwright

    from app.charts import new_chart_path, prune_charts

    path = new_chart_path()
    html_path = path.with_suffix(".html")
    html_path.write_text(build_html(collect(usage, now=now)), encoding="utf-8")
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": CARD_WIDTH, "height": 1200},
                )
                page.set_default_timeout(RENDER_TIMEOUT_MS)
                await page.goto(html_path.as_uri())
                await page.screenshot(path=str(path), full_page=True)
            finally:
                await browser.close()
    finally:
        html_path.unlink(missing_ok=True)
    prune_charts()
    return str(path)
