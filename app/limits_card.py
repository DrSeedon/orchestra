"""Картинка `/limits`: вложенная шкала недели и пятичасового окна, HTML → PNG.

Почему HTML, а не Pillow как в `app/charts.py`: здесь не график, а вёрстка — вложенные
полосы, насечки, двухстрочные строки пулов. Руками по пикселям это не поддерживается.

Оконная арифметика (сколько окна прошло и обгоняет ли расход календарь) живёт тоже здесь и
используется И картинкой, И текстом под ней (`_format_limits_message_for_chat`), чтобы
цифры в подписи и на картинке не разъезжались.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging
import math
from bisect import bisect_right
from pathlib import Path


_renderer_lock: asyncio.Lock | None = None
_renderer_loop = None
_renderer_playwright = None
_renderer_browser = None
logger = logging.getLogger("orchestra.limits_card")

# Порог темпа зеркалит фронтовый `_paceIndicator` (app/static/js/usage.js:46):
# отставание в 5 п.п. от календаря считается нормой, дальше — обгон.
PACE_OK_DELTA = 5.0
PACE_WARN_DELTA = 20.0
WINDOW_FALLBACK_MINUTES = {"five_hour": 300, "seven_day": 10080}

LOCAL_TZ = dt.timezone(dt.timedelta(hours=7))
RENDER_TIMEOUT_MS = 20_000
CARD_WIDTH = 900
HISTORY_HOURS = 168  # usage.js: _SPARK_VIEW_HOURS
HISTORY_TIMEOUT_SECONDS = 3
POOL_HISTORY_KEYS = (
    ("anthropic", "five_hour"), ("anthropic", "seven_day"),
    ("codex", "primary"), ("codex", "secondary"),
    ("codex_spark", "primary"), ("grok", "primary"),
)

P = {
    "bg": "#0a0e17", "panel": "#111827", "border": "#334155",
    "ink": "#e2e8f0", "soft": "#a6b3c6", "faint": "#8595ab",
    "accent": "#818cf8", "alt": "#38bdf8",
    "ok": "#22c55e", "warn": "#eab308", "danger": "#ef4444",
}


async def _close_renderer_resources(browser, playwright) -> None:
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            await playwright.stop()
        except Exception:
            pass


async def _close_renderer() -> None:
    global _renderer_playwright, _renderer_browser
    browser, playwright = _renderer_browser, _renderer_playwright
    _renderer_browser = None
    _renderer_playwright = None
    await _close_renderer_resources(browser, playwright)


def _release_renderer_from_previous_loop(old_loop) -> None:
    global _renderer_playwright, _renderer_browser
    browser, playwright = _renderer_browser, _renderer_playwright
    _renderer_browser = None
    _renderer_playwright = None
    if browser is None and playwright is None:
        return
    if old_loop.is_running() and not old_loop.is_closed():
        future = asyncio.run_coroutine_threadsafe(
            _close_renderer_resources(browser, playwright), old_loop,
        )

        def consume_cleanup_error(done) -> None:
            try:
                done.result()
            except Exception as error:
                logger.warning("renderer cleanup on previous loop failed: %s: %s",
                               type(error).__name__, error)

        future.add_done_callback(consume_cleanup_error)
        return
    logger.warning(
        "renderer resources released without await: previous event loop is %s",
        "closed" if old_loop.is_closed() else "not running",
    )


async def shutdown_renderer() -> None:
    """Close the persistent browser on the application's running event loop."""
    global _renderer_lock, _renderer_loop
    if _renderer_loop is not None and _renderer_loop is not asyncio.get_running_loop():
        # Браузер поднят на другом цикле: ответ Playwright придёт туда, а не сюда, и
        # `browser.close()` здесь ждал бы вечно. V-624: так висел lifespan-teardown
        # второго `TestClient`, когда карточку рендерил цикл первого.
        _release_renderer_from_previous_loop(_renderer_loop)
    elif _renderer_lock is not None:
        async with _renderer_lock:
            await _close_renderer()
    else:
        await _close_renderer()
    _renderer_lock = None
    _renderer_loop = None


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

def _finite_number(value) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _new_period(previous: dict, point: dict) -> bool:
    """usage.js _usagePeriods: reset drift ≤1h belongs to the same window."""
    before, after = previous["reset"], point["reset"]
    return (previous["minutes"] != point["minutes"]
            or bool(before and after and abs((after - before).total_seconds()) > 3600))


def collect_history(history: dict, now: dt.datetime) -> dict:
    """Front's latest longest-window period, with real samples instead of grid carry.

    `sample_ts` retains the stored time when the canonical API resamples a row.
    Missing windows, gaps and reset boundaries never become connecting lines.
    """
    series, observed = {}, {}
    for row in history.get("rows") or []:
        providers = row.get("providers")
        if not isinstance(providers, dict):
            # Old Claude-only responses, same fallback as usage.js _historyProviders.
            windows = []
            for key, minutes in (("five_hour", 300), ("seven_day", 10080)):
                value = _finite_number(row.get(f"{key}_pct"))
                reset = row.get(f"{key}_resets_at")
                if value is not None and (reset or value == 0):
                    windows.append(dict(id=key, utilization=value,
                                        window_minutes=minutes, resets_at=reset))
            providers = {"anthropic": {"windows": windows}}
        ts = to_utc(row.get("sample_ts") or row.get("ts"))
        if ts is None or not now - dt.timedelta(hours=HISTORY_HOURS) <= ts <= now:
            continue
        present = observed.setdefault(ts, set())
        for provider_id, provider in providers.items():
            for window in provider.get("windows") or []:
                used = _finite_number(window.get("utilization"))
                minutes = _finite_number(window.get("window_minutes"))
                if used is None or not 0 <= used <= 100 or minutes is None or minutes <= 0:
                    continue
                key = (provider_id, window.get("id"))
                present.add(key)
                series.setdefault(key, {})[ts] = dict(
                    ts=ts, used=used, minutes=minutes, reset=to_utc(window.get("resets_at")),
                )
    series = {key: sorted(points.values(), key=lambda p: p["ts"])
              for key, points in series.items()}
    anchors = {}
    for provider_id in {key[0] for key in series}:
        candidates = [points for key, points in series.items() if key[0] == provider_id]
        anchor = max(candidates, key=lambda points: points[0]["minutes"])
        periods = []
        for point in anchor:
            if not periods or _new_period(periods[-1][-1], point):
                periods.append([])
            periods[-1].append(point)
        trimmed = []
        for period in periods:
            last = period[-1]
            start = (last["reset"] - dt.timedelta(minutes=last["minutes"])
                     if last["reset"] else period[0]["ts"])
            trimmed.append([p for p in period if p["ts"] >= start])
        # Front requires two points. A lone measurement is still useful as a dot.
        eligible = [period for period in trimmed if len(period) >= 2]
        selected = eligible[-1] if eligible else next((p for p in reversed(trimmed) if p), [])
        if selected:
            anchors[provider_id] = (selected[0]["ts"], selected[-1]["ts"])
    step = _finite_number(history.get("step_minutes")) or 5
    gap = dt.timedelta(minutes=max(1, step) * 1.5)
    result = {}
    for key, points in series.items():
        bounds = anchors.get(key[0])
        if bounds is None:
            continue
        selected = [p for p in points if bounds[0] <= p["ts"] <= bounds[1]]
        missing = sorted(ts for ts, keys in observed.items() if key not in keys)
        segments = []
        for point in selected:
            previous = segments[-1][-1] if segments else None
            absent = (previous is not None
                      and bisect_right(missing, previous["ts"]) < bisect_right(missing, point["ts"]))
            if (previous is None or point["ts"] - previous["ts"] > gap
                    or absent or _new_period(previous, point)):
                segments.append([])
            segments[-1].append(point)
        if selected:
            result[key] = dict(start=bounds[0], end=bounds[1], segments=segments,
                               last=selected[-1], stale=now - selected[-1]["ts"] > gap)
    return result


def collect(usage: dict, *, now: dt.datetime | None = None,
            history: dict | None = None) -> dict:
    """Ответ `/api/usage` → всё, что рисует карточка. Ничего не считает про окна недели:
    это работа `_quota_headroom`, отсутствует она — отсутствует и блок недели."""
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

    spark = codex.get("spark") or {}
    # Недельное окно Codex лежит в `secondary` и останавливает работу так же, как
    # пятичасовое, — рисуем обе полосы, иначе картинка показывает ноль расхода у
    # провайдера, который на самом деле закрыт до конца недели.
    pools = [
        pool("Claude · 5 часов", anthropic.get("five_hour"), "five_hour"),
        pool("Claude · неделя", anthropic.get("seven_day"), "seven_day"),
        pool("Codex · 5 часов", codex.get("primary"), "five_hour"),
        pool("Codex · неделя", codex.get("secondary"), "seven_day"),
        pool("Spark · 5 часов", spark.get("primary"), "five_hour"),
        pool("Grok", (usage.get("grok") or {}).get("primary")),
    ]
    histories = collect_history(history or {}, now)
    for p, key in zip(pools, POOL_HISTORY_KEYS):
        p["history"] = histories.get(key)
        p["history_unavailable"] = bool(history and history.get("unavailable"))

    head = usage.get("quota_headroom")
    week = None
    if (isinstance(head, dict)
            and isinstance(head.get("rate"), (int, float))
            and not isinstance(head["rate"], bool)
            and math.isfinite(head["rate"])
            and head["rate"] > 0
            and isinstance(head.get("windows_left"), (int, float))
            and not isinstance(head["windows_left"], bool)
            and math.isfinite(head["windows_left"])
            and head["windows_left"] > 0):
        five_used = pools[0]["used"] or 0.0
        week_used = pools[1]["used"] or 0.0
        cost = head["rate"] * 100
        week = {
            "cost": cost,
            "total": 100 / cost,
            "spent": week_used / cost,
            "left": float(head["windows_left"]),
            "week_used": week_used,
            "five_used": five_used,
            "visible_pct": max(0.0, 100 - five_used),
            "available_pct": float(head.get("available_pct") or 0.0),
            "locked_pct": float(head.get("locked_pct") or 0.0),
            "reset": pools[1].get("reset") or "",
        }
    return {"now": now, "pools": pools, "week": week}


# ── вёрстка ───────────────────────────────────────────────────────────────────

def _css() -> str:
    return f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{CARD_WIDTH}px; background:{P['bg']}; color:{P['ink']}; padding:40px 40px 34px;
  font-family:'DejaVu Sans','Noto Sans',system-ui,sans-serif; }}
.head {{ font-size:30px; color:{P['faint']}; letter-spacing:1px; }}
.huge {{ font-size:76px; font-weight:700; line-height:1.08; margin-top:6px; }}
.sub {{ font-size:34px; color:{P['soft']}; margin-top:16px; line-height:1.4; }}
.cap {{ font-size:31px; color:{P['soft']}; margin-top:32px; line-height:1.4; }}
.week {{ margin-top:16px; height:96px; border-radius:16px; background:#161f31;
  border:2px solid {P['border']}; position:relative; overflow:hidden; }}
.week .burn {{ position:absolute; inset:0 auto 0 0; background:{P['danger']}; opacity:.85; }}
.week .tick {{ position:absolute; top:0; bottom:0; width:2px; background:{P['bg']}; opacity:.6; }}
.week .lbl {{ position:absolute; top:28px; left:22px; font-size:32px; font-weight:700;
  color:#fff; text-shadow:0 2px 6px #000; }}
.axis {{ display:flex; justify-content:space-between; margin-top:12px; font-size:28px;
  color:{P['faint']}; }}
.five {{ margin-top:16px; height:76px; border-radius:16px; background:#161f31;
  border:2px solid {P['border']}; position:relative; overflow:hidden; }}
.five .burn {{ position:absolute; top:0; bottom:0; background:{P['danger']}; opacity:.85; }}
.five .avail {{ position:absolute; top:0; bottom:0; background:{P['ok']}; opacity:.34; }}
.five .locked {{ position:absolute; top:0; bottom:0;
  background:repeating-linear-gradient(135deg,#2b3448 0 10px,#1b2233 10px 20px); }}
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
  gap:6px 16px; flex-wrap:wrap; white-space:nowrap; }}
.pool .rs {{ color:{P['faint']}; }}
.pool .nm, .pool .vl {{ white-space:nowrap; }}
.nodata {{ font-size:29px; color:{P['faint']}; font-style:italic; margin-top:6px; }}
.history {{ margin-top:12px; }}
.history-note {{ font-size:22px; color:{P['soft']}; margin:8px 0; }}
.history svg {{ display:block; width:100%; height:146px; }}
"""


def _history_html(pool: dict) -> str:
    data = pool.get("history")
    if not data:
        note = "история недоступна" if pool.get("history_unavailable") else "истории нет"
        return f'<div class="history-note">{note}</div>'
    start, end = data["start"], data["end"]
    span = max(1, (end - start).total_seconds())
    left, right, top, bottom = 62, 806, 10, 108
    x = lambda point: left + (point["ts"] - start).total_seconds() / span * (right - left)
    y = lambda value: bottom - value / 100 * (bottom - top)
    parts = [f'<svg viewBox="0 0 820 146" role="img" aria-label="История расхода, проценты">']
    for value in (0, 50, 100):
        parts.append(f'<line x1="{left}" x2="{right}" y1="{y(value):.1f}" '
                     f'y2="{y(value):.1f}" stroke="{P["border"]}"/>'
                     f'<text x="52" y="{y(value) + 7:.1f}" text-anchor="end" '
                     f'fill="{P["faint"]}" font-size="20">{value}%</text>')
    for segment in data["segments"]:
        if len(segment) >= 2:
            coords = " ".join(f'{x(p):.1f},{y(p["used"]):.1f}' for p in segment)
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{P["alt"]}" '
                         'stroke-width="3" stroke-linejoin="round"/>')
        # Ideal pace needs real reset metadata; its absence is not 0% elapsed.
        ideal = []
        for point in segment:
            if point["reset"] is None:
                if len(ideal) >= 2:
                    parts.append(_ideal_line(ideal))
                ideal = []
                continue
            elapsed = 100 - (point["reset"] - point["ts"]).total_seconds() / (point["minutes"] * 60) * 100
            ideal.append(f'{x(point):.1f},{y(max(0, min(100, elapsed))):.1f}')
        if len(ideal) >= 2:
            parts.append(_ideal_line(ideal))
        for point in segment:
            parts.append(f'<circle cx="{x(point):.1f}" cy="{y(point["used"]):.1f}" '
                         f'r="3" fill="{P["alt"]}"/>')
    for when, at, align in ((start, left, "start"), (end, right, "end")):
        label = when.astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")
        parts.append(f'<text x="{at}" y="140" text-anchor="{align}" '
                     f'fill="{P["soft"]}" font-size="21">{label}</text>')
    parts.append('</svg>')
    last = data["last"]
    stamp = last["ts"].astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")
    status = " · устарело" if data["stale"] else ""
    note = f'История · последнее {last["used"]:.1f}% в {stamp}{status}'
    return f'<div class="history"><div class="history-note">{note}</div>{"".join(parts)}</div>'


def _ideal_line(coords: list[str]) -> str:
    return (f'<polyline points="{" ".join(coords)}" fill="none" stroke="{P["faint"]}" '
            'stroke-width="2" stroke-dasharray="6 5"/>')


def _pools_html(pools: list[dict]) -> str:
    rows = []
    for p in pools:
        name = html.escape(p["label"])
        if p["used"] is None:
            rows.append(
                f'<div class="pool"><div class="top"><span class="nm">{name}</span></div>'
                f'<div class="nodata">нет данных — сервис не ответил</div>{_history_html(p)}</div>'
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
            f'<span class="rs">{html.escape(p["reset"])}</span></div>{_history_html(p)}</div>'
        )
    return f'<div class="pools">{"".join(rows)}</div>'


def build_html(data: dict) -> str:
    stamp = data["now"].astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")
    week = data["week"]
    if week is None:
        top = (
            f'<div class="huge">Курс не измерен</div>'
            f'<div class="sub">Сколько пятичасовых окон осталось — посчитать нечем: нет '
            f'истории расхода. Ниже только сами окна, без пересчёта одного в другое.</div>'
        )
    else:
        ticks = "".join(
            f'<div class="tick" style="left:{k / week["total"] * 100:.2f}%"></div>'
            for k in range(1, int(week["total"]) + 1)
        )
        five_used, avail, locked = week["five_used"], week["available_pct"], week["locked_pct"]
        top = (
            f'<div class="huge">Недели хватит на '
            f'<span style="color:{P["warn"]}">{week["left"]:.1f}</span> окна</div>'
            f'<div class="sub">Пятичасовое окно свободно на {week["visible_pct"]:.0f}%, но '
            f'взять из него можно только {avail:.0f}% — остальное упирается в недельный запас.</div>'
            f'<div class="cap">Полоса ниже — вся неделя. Насечки делят её на пятичасовые '
            f'окна: их помещается {week["total"]:.1f}.</div>'
            f'<div class="week"><div class="burn" style="width:{week["week_used"]:.1f}%"></div>'
            f'{ticks}<div class="lbl">сожжено {week["spent"]:.1f} окна</div></div>'
            f'<div class="axis"><span>вся неделя = {week["total"]:.1f} окна</span>'
            f'<span style="color:{P["ok"]}">осталось {week["left"]:.1f} · '
            f'до {html.escape(week["reset"].split("·")[-1].strip())}</span></div>'
            f'<div class="cap">А это ближайшие 5 часов. Зелёное — сколько на самом деле можно '
            f'взять, полосатое — то, что недельный запас уже не пустит.</div>'
            f'<div class="five"><div class="burn" style="left:0;width:{five_used:.1f}%"></div>'
            f'<div class="avail" style="left:{five_used:.1f}%;width:{avail:.1f}%"></div>'
            f'<div class="locked" style="left:{five_used + avail:.1f}%;width:{locked:.1f}%"></div></div>'
            f'<div class="axis"><span>сожжено {five_used:.0f}%</span>'
            f'<span style="color:{P["ok"]}">доступно {avail:.0f}%</span>'
            f'<span>заперто неделей {locked:.0f}%</span></div>'
        )
    return (
        f"<!doctype html><meta charset='utf-8'><style>{_css()}</style><body>"
        f'<div class="head">ЛИМИТЫ · {stamp} · UTC+7</div>{top}'
        f'<div class="history-note">История · последний период каждого провайдера · до 7 суток<br>'
        f'━ расход, % · ┄ прошло окна, % · разрывы: нет снимков / сброс</div>'
        f'{_pools_html(data["pools"])}'
        f"</body>"
    )


async def render_limits_card(usage: dict, *, now: dt.datetime | None = None,
                             history: dict | None = None) -> str:
    """HTML → PNG. Путь к файлу. Кидает наружу — вызывающий откатывается на текст."""
    from playwright.async_api import async_playwright

    from app.charts import new_chart_path, prune_charts

    global _renderer_lock, _renderer_loop, _renderer_playwright, _renderer_browser
    if history is None:
        from app.routes.system import usage_history_data

        try:
            history = await asyncio.wait_for(
                asyncio.to_thread(usage_history_data, HISTORY_HOURS), HISTORY_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logger.warning("limits history unavailable: %s", type(error).__name__)
            history = {"unavailable": True}
    path = new_chart_path()
    html_path = path.with_suffix(".html")
    html_path.write_text(build_html(collect(usage, now=now, history=history)), encoding="utf-8")
    try:
        loop = asyncio.get_running_loop()
        if _renderer_loop is not None and _renderer_loop is not loop:
            _release_renderer_from_previous_loop(_renderer_loop)
            _renderer_lock = None
        if _renderer_lock is None:
            _renderer_loop = loop
            _renderer_lock = asyncio.Lock()
        async with _renderer_lock:
            for attempt in range(2):
                page = None
                try:
                    if (_renderer_browser is None
                            or not _renderer_browser.is_connected()):
                        if _renderer_playwright is None:
                            _renderer_playwright = await async_playwright().start()
                        _renderer_browser = await _renderer_playwright.chromium.launch()
                    page = await _renderer_browser.new_page(
                        viewport={"width": CARD_WIDTH, "height": 1200},
                    )
                    page.set_default_timeout(RENDER_TIMEOUT_MS)
                    await page.goto(html_path.as_uri())
                    await page.screenshot(path=str(path), full_page=True)
                    break
                except Exception:
                    await _close_renderer()
                    if attempt:
                        raise
                finally:
                    if page is not None:
                        try:
                            await page.close()
                        except Exception:
                            pass
    finally:
        html_path.unlink(missing_ok=True)
    prune_charts()
    return str(path)
