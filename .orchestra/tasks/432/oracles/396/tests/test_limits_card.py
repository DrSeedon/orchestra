"""#274: картинка `/limits` — вложенная шкала недели и пятичасового окна."""
import datetime as dt
from unittest.mock import AsyncMock

import pytest

from app.limits_card import build_html, collect

NOW = dt.datetime(2026, 8, 14, 8, 0, 0, tzinfo=dt.timezone.utc)


def _iso(minutes_ahead: float) -> str:
    return (NOW + dt.timedelta(minutes=minutes_ahead)).isoformat()


def _usage(**over) -> dict:
    usage = {
        "anthropic": {
            "five_hour": {"utilization": 4.0, "resets_at": _iso(270)},
            "seven_day": {"utilization": 88.0, "resets_at": _iso(5700)},
        },
        "codex": {
            "primary": {"utilization": 97, "window_minutes": 10080, "resets_at": _iso(8300)},
            "spark": {"primary": {"utilization": 9, "window_minutes": 10080,
                                  "resets_at": _iso(8400)}},
        },
        "grok": {},
        "quota_headroom": {"rate": 0.1319, "available_pct": 91.0, "locked_pct": 5.0,
                           "windows_left": 0.91, "window_hours": 72},
    }
    usage.update(over)
    return usage


def test_headroom_gives_the_headline_and_the_nested_scale():
    html = build_html(collect(_usage(), now=NOW))

    assert "Недели хватит на" in html and ">0.9</span> окна" in html
    assert "их помещается 7.6" in html
    assert "свободно на 96%" in html and "только 91%" in html
    assert "заперто неделей 5%" in html


def test_without_headroom_the_card_says_rate_is_not_measured():
    """Курс не измерен — нельзя показывать ложный нулевой остаток окон."""
    html = build_html(collect(_usage(quota_headroom=None), now=NOW))

    assert "Курс не измерен" in html
    assert "Недели хватит" not in html
    assert "окна</div>" not in html
    assert "занято 88%" in html and "Claude · неделя" in html


def test_card_and_chat_use_the_same_headroom_window_count():
    from app.tg_bridge import _format_limits_message_for_chat

    usage = _usage(
        quota_headroom={"rate": 0.1319, "available_pct": 91.0,
                        "locked_pct": 5.0, "windows_left": 0.42},
    )
    html = build_html(collect(usage, now=NOW))
    message = _format_limits_message_for_chat(usage, now=NOW)

    assert collect(usage, now=NOW)["week"]["left"] == 0.42
    assert ">0.4</span> окна" in html
    assert "— 0.42" in message


def test_quota_headroom_rejects_non_finite_or_boolean_values(monkeypatch):
    import app.routes.system as system

    monkeypatch.setattr(system, "_headroom_cache_key", None)
    anthropic = {
        "five_hour": {"utilization": True},
        "seven_day": {"utilization": 88.0},
    }
    assert system._quota_headroom(anthropic) is None

    anthropic["five_hour"]["utilization"] = float("nan")
    assert system._quota_headroom(anthropic) is None


def test_quota_headroom_caches_history_for_sixty_seconds(monkeypatch):
    import app.db as db
    import app.routes.system as system

    calls = 0

    def measured():
        nonlocal calls
        calls += 1
        return {"rate": 0.13, "five_hour_pct_sum": 40.0, "window_hours": 72}

    monkeypatch.setattr(db, "usage_exchange_rate", measured)
    monkeypatch.setattr(system, "_headroom_cache_key", None)
    anthropic = _usage()["anthropic"]

    assert system._quota_headroom(anthropic)["windows_left"] == 0.92
    assert system._quota_headroom(anthropic)["windows_left"] == 0.92
    assert calls == 1

    monkeypatch.setattr(system, "_headroom_cache_ts", system.time.monotonic() - 61)
    assert system._quota_headroom(anthropic)["windows_left"] == 0.92
    assert calls == 2


@pytest.mark.parametrize(
    "used, minutes_left, expected_pace, expected_colour",
    [
        # 90% сожжено за 95% окна — это норма, календарь не обогнан
        (90.0, 15, "в графике", "#22c55e"),
        # 30% за 5% окна — беда, хотя абсолютный процент маленький
        (30.0, 285, "обгон +25 п.п.", "#ef4444"),
        # небольшой обгон — жёлтый, не красный
        (20.0, 270, "обгон +10 п.п.", "#eab308"),
    ],
)
def test_colour_encodes_overtaking_the_calendar_not_the_absolute_percent(
    used, minutes_left, expected_pace, expected_colour,
):
    usage = _usage()
    usage["anthropic"]["five_hour"] = {"utilization": used, "resets_at": _iso(minutes_left)}

    five = collect(usage, now=NOW)["pools"][0]

    assert five["pace"] == expected_pace
    assert five["color"] == expected_colour


def test_pool_without_data_is_honest_and_uncoloured():
    """Grok отдаёт `{}`. Придуманный темп хуже отсутствующего."""
    grok = collect(_usage(), now=NOW)["pools"][4]

    assert grok["label"] == "Grok" and grok["used"] is None
    assert grok["pace"] is None and grok["color"] is None
    html = build_html(collect(_usage(), now=NOW))
    assert "нет данных — сервис не ответил" in html


def test_every_pool_shows_burn_against_elapsed_window():
    """Юзер просил рядом с расходом видеть, сколько окна прошло — по всем пяти.

    Сверяем ПОПУЛЬНО, а не поиском подстроки по всему html: проценты у пулов совпадают,
    и ассерт про Codex зеленел на строке Spark (поймано первым же прогоном).
    """
    pools = collect(_usage(), now=NOW)["pools"]

    assert [(p["label"], p["used"], p["elapsed"]) for p in pools] == [
        ("Claude · 5 часов", 4.0, 10),
        ("Claude · неделя", 88.0, 43),
        ("Codex", 97.0, 18),
        ("Spark", 9.0, 17),
        ("Grok", None, None),
    ]
    # Grok без данных — строку про окно ему не дорисовываем
    assert build_html(collect(_usage(), now=NOW)).count("окно прошло") == 4


@pytest.mark.asyncio
async def test_limits_usage_carries_quota_headroom(monkeypatch):
    """`/limits` и `/api/usage` используют один расчёт headroom."""
    import app.routes.system as system
    import app.tg_bridge as tb

    raw = {"anthropic": {}}
    monkeypatch.setattr(system, "_get_usage_data", AsyncMock(return_value=raw))
    monkeypatch.setattr(system, "_quota_headroom", lambda anthropic: {"rate": 0.13})

    assert (await tb._get_limits_usage())["quota_headroom"] == {"rate": 0.13}


@pytest.mark.asyncio
async def test_usage_card_endpoint_uses_the_canonical_renderer(monkeypatch, tmp_path):
    """Other local clients must receive the same PNG as Orchestra's Telegram bridge."""
    import app.limits_card as card
    import app.routes.system as system

    png = tmp_path / "limits.png"
    png.write_bytes(b"png")
    raw = {"anthropic": {}}
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(system, "_get_usage_data", AsyncMock(return_value=raw))
    monkeypatch.setattr(system, "_quota_headroom", lambda anthropic: {"rate": 0.13})
    render = AsyncMock(return_value=str(png))
    monkeypatch.setattr(card, "render_limits_card", render)

    response = await system.get_usage_card()

    render.assert_awaited_once_with({"anthropic": {}, "quota_headroom": {"rate": 0.13}})
    assert response.path == str(png)
    assert response.media_type == "image/png"
    assert response.filename == "limits.png"


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_renderer_does_not_await_resources_from_closed_loop(monkeypatch, tmp_path):
    import asyncio
    import app.charts as charts
    import app.limits_card as card
    import playwright.async_api as playwright_api

    class Page:
        def set_default_timeout(self, timeout):
            pass

        async def goto(self, url):
            pass

        async def screenshot(self, *, path, full_page):
            tmp_path.joinpath("rendered.png").write_bytes(b"png")

        async def close(self):
            pass

    class Browser:
        def __init__(self):
            self.close_calls = 0

        def is_connected(self):
            return True

        async def new_page(self, **kwargs):
            return Page()

        async def close(self):
            self.close_calls += 1

    class Playwright:
        def __init__(self, browser):
            self.browser = browser
            self.chromium = self
            self.stop_calls = 0

        async def launch(self):
            return self.browser

        async def stop(self):
            self.stop_calls += 1

    old_browser, old_playwright = AsyncMock(), AsyncMock()
    old_browser.close.side_effect = AssertionError("closed-loop browser must not be awaited")
    old_playwright.stop.side_effect = AssertionError("closed-loop playwright must not be awaited")
    old_loop = asyncio.new_event_loop()
    old_loop.close()
    new_browser = Browser()
    new_playwright = Playwright(new_browser)

    class Factory:
        async def start(self):
            return new_playwright

    monkeypatch.setattr(playwright_api, "async_playwright", lambda: Factory())
    monkeypatch.setattr(charts, "new_chart_path", lambda: tmp_path / "limits.png")
    monkeypatch.setattr(charts, "prune_charts", lambda: None)
    monkeypatch.setattr(card, "_renderer_loop", old_loop)
    monkeypatch.setattr(card, "_renderer_lock", asyncio.Lock())
    monkeypatch.setattr(card, "_renderer_browser", old_browser)
    monkeypatch.setattr(card, "_renderer_playwright", old_playwright)

    path = await card.render_limits_card({})

    assert path == str(tmp_path / "limits.png")
    old_browser.close.assert_not_awaited()
    old_playwright.stop.assert_not_awaited()
    await card.shutdown_renderer()


@pytest.mark.asyncio
async def test_renderer_shutdown_closes_browser_and_playwright(monkeypatch):
    import asyncio
    import app.limits_card as card

    browser = AsyncMock()
    playwright = AsyncMock()
    monkeypatch.setattr(card, "_renderer_loop", asyncio.get_running_loop())
    monkeypatch.setattr(card, "_renderer_lock", asyncio.Lock())
    monkeypatch.setattr(card, "_renderer_browser", browser)
    monkeypatch.setattr(card, "_renderer_playwright", playwright)

    await card.shutdown_renderer()

    browser.close.assert_awaited_once_with()
    playwright.stop.assert_awaited_once_with()
    assert card._renderer_browser is None
    assert card._renderer_playwright is None
    assert card._renderer_loop is None
    assert card._renderer_lock is None
