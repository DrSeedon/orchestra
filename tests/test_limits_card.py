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
    grok = next(p for p in collect(_usage(), now=NOW)["pools"] if p["label"] == "Grok")

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
        ("Codex · 5 часов", 97.0, 18),
        ("Codex · неделя", None, None),
        ("Spark · 5 часов", 9.0, 17),
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
@pytest.mark.timeout(10)
async def test_shutdown_does_not_await_browser_of_another_loop(monkeypatch):
    """V-624: браузер другого цикла на `close()` не отвечает никогда — shutdown не ждёт его."""
    import asyncio
    import app.limits_card as card

    async def never(*_args):
        await asyncio.Event().wait()

    browser, playwright = AsyncMock(), AsyncMock()
    browser.close.side_effect = never
    playwright.stop.side_effect = never
    old_loop = asyncio.new_event_loop()
    old_loop.close()
    monkeypatch.setattr(card, "_renderer_loop", old_loop)
    monkeypatch.setattr(card, "_renderer_lock", asyncio.Lock())
    monkeypatch.setattr(card, "_renderer_browser", browser)
    monkeypatch.setattr(card, "_renderer_playwright", playwright)

    await asyncio.wait_for(card.shutdown_renderer(), 2)

    browser.close.assert_not_awaited()
    assert card._renderer_browser is None
    assert card._renderer_loop is None


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


def test_codex_weekly_window_is_shown_next_to_the_five_hour_one():
    """#V-597: 16.09 недельное окно Codex встало на 100% и остановило работу на трое
    суток, а `/limits` показывал только пятичасовое — ноль расхода у закрытого
    провайдера. Обе строки обязаны быть и в сообщении, и на картинке."""
    from app.tg_bridge import _format_limits_message_for_chat

    usage = _usage(codex={
        "primary": {"utilization": 0, "window_minutes": 300, "resets_at": _iso(120)},
        "secondary": {"utilization": 100, "window_minutes": 10080, "resets_at": _iso(4000)},
    })

    message = _format_limits_message_for_chat(usage, now=NOW)
    five_hour = next(l for l in message.splitlines() if l.startswith("• Codex 5h"))
    weekly = next(l for l in message.splitlines() if l.startswith("• Codex 7d"))
    assert "израсходовано 0%" in five_hour, five_hour
    assert "израсходовано 100%" in weekly, weekly
    assert "осталось 0%" in weekly, weekly

    html = build_html(collect(usage, now=NOW))
    assert "Codex · 5 часов" in html and "Codex · неделя" in html


def test_codex_weekly_window_counts_its_own_window_progress():
    """Прогресс недели считается по недельной длительности, а не по пятичасовой:
    иначе окно «пройдено на 100%» у только что открывшейся недели."""
    from app.limits_card import collect

    # Длительность окна провайдер присылает не всегда — без неё её берут по имени окна,
    # и перепутанное имя даёт «неделя пройдена на 100%» в первый же час.
    usage = _usage(codex={
        "primary": {"utilization": 10, "resets_at": _iso(150)},
        "secondary": {"utilization": 10, "resets_at": _iso(9000)},
    })
    pools = {p["label"]: p for p in collect(usage, now=NOW)["pools"]}

    assert pools["Codex · 5 часов"]["elapsed"] == 50
    assert pools["Codex · неделя"]["elapsed"] == 11


# V-1082: the PNG consumes the same multi-provider snapshot contract as usage.js.
def _history_window(key="primary", value=20, minutes=300, reset=None):
    return dict(id=key, utilization=value, window_minutes=minutes,
                resets_at=reset or _iso(60))


def _history_row(minutes_ago, **providers):
    return dict(ts=_iso(-minutes_ago), providers={
        key: {"windows": windows} for key, windows in providers.items()
    })


def _history(*rows, step=5):
    return dict(rows=list(rows), step_minutes=step)


def test_history_maps_each_metric_and_preserves_missing_spark_and_grok():
    from app.limits_card import collect_history

    result = collect_history(_history(*[
        _history_row(ago,
            anthropic=[_history_window("five_hour", 12, 300),
                       _history_window("seven_day", 63, 10080)],
            codex=[_history_window("primary", 25, 300),
                   _history_window("secondary", 47, 10080)],
        ) for ago in (10, 5)
    ]), NOW)
    assert {key: data["last"]["used"] for key, data in result.items()} == {
        ("anthropic", "five_hour"): 12, ("anthropic", "seven_day"): 63,
        ("codex", "primary"): 25, ("codex", "secondary"): 47,
    }
    data = collect(_usage(), now=NOW, history=_history(*[
        _history_row(ago, codex_spark=[_history_window(value=9)],
                     grok=[_history_window(value=0, minutes=120)]) for ago in (10, 5)
    ]))
    assert data["pools"][4]["history"]["last"]["used"] == 9
    assert data["pools"][5]["history"]["last"]["used"] == 0
    assert data["pools"][5]["history"]["last"]["minutes"] == 120


@pytest.mark.parametrize("invalid", [None, "", True, float("nan"), float("inf"), -1, 101])
def test_absent_or_invalid_history_values_are_not_zero(invalid):
    from app.limits_card import collect_history

    history = _history(_history_row(5, grok=[_history_window(value=invalid)]))
    assert ("grok", "primary") not in collect_history(history, NOW)


def test_old_claude_columns_do_not_invent_other_providers():
    from app.limits_card import collect_history

    history = _history(dict(ts=_iso(-5), five_hour_pct=0,
                            seven_day_pct=None, seven_day_resets_at=_iso(50)))
    result = collect_history(history, NOW)
    assert set(result) == {("anthropic", "five_hour")}
    assert result[("anthropic", "five_hour")]["last"]["used"] == 0


def test_history_latest_longest_window_anchors_both_series():
    from app.limits_card import collect_history

    rows = []
    for ago in (120, 115, 10, 5):
        weekly_reset = _iso(-60) if ago > 60 else _iso(10020)
        rows.append(_history_row(ago, codex=[
            _history_window(value=ago, reset=_iso(60)),
            _history_window("secondary", 35, 10080, weekly_reset),
        ]))
    result = collect_history(_history(*rows), NOW)
    for key in (("codex", "primary"), ("codex", "secondary")):
        assert result[key]["start"] == NOW - dt.timedelta(minutes=10)
        assert result[key]["end"] == NOW - dt.timedelta(minutes=5)
        assert len(result[key]["segments"][0]) == 2


def test_history_clips_to_window_start_and_does_not_bridge_short_resets():
    from app.limits_card import collect_history

    rows = [_history_row(ago, codex=[
        _history_window(value=30 if ago > 10 else 5,
                        reset=_iso(-10) if ago > 10 else _iso(290)),
        _history_window("secondary", 35, 10080, _iso(10070)),
    ]) for ago in (20, 15, 10, 5)]
    # Weekly window started ten minutes ago: pre-window points are excluded.
    result = collect_history(_history(*rows), NOW)
    assert result[("codex", "primary")]["start"] == NOW - dt.timedelta(minutes=10)
    # Move week start back, keeping the short-window reset inside the shared slice.
    for row in rows:
        row["providers"]["codex"]["windows"][1]["resets_at"] = _iso(9900)
    result = collect_history(_history(*rows), NOW)
    assert [len(s) for s in result[("codex", "primary")]["segments"]] == [2, 2]


@pytest.mark.parametrize("change", ["gap", "missing", "duration"])
def test_history_does_not_connect_missing_samples_or_different_durations(change):
    from app.limits_card import collect_history

    times = (65, 60, 10, 5) if change == "gap" else (20, 15, 10, 5)
    rows = [_history_row(ago, codex=[
        _history_window(value=20, minutes=120 if change == "duration" and ago <= 10 else 300),
        _history_window("secondary", 35, 10080, _iso(9900)),
    ]) for ago in times]
    if change == "missing":
        rows[1]["providers"]["codex"]["windows"].pop(0)
    result = collect_history(_history(*rows), NOW)[("codex", "primary")]
    assert [len(s) for s in result["segments"]] == ([1, 2] if change == "missing" else [2, 2])


def test_single_stale_sample_keeps_its_time_without_extension_or_grid_duplicates():
    from app.limits_card import collect_history

    first = _history_row(120, grok=[_history_window(value=34)])
    duplicate = dict(first, ts=_iso(-115), sample_ts=first["ts"])
    result = collect_history(_history(first, duplicate), NOW)[("grok", "primary")]
    assert result["start"] == result["end"] == NOW - dt.timedelta(minutes=120)
    assert result["stale"] is True
    assert [len(s) for s in result["segments"]] == [1]


def test_chart_coordinates_use_percent_units_and_actual_shared_time():
    import re
    import xml.etree.ElementTree as ET

    history = _history(*[
        _history_row(ago, grok=[_history_window(value=value, minutes=120, reset=_iso(60))])
        for ago, value in ((15, 0), (10, 50), (5, 100))
    ])
    source = build_html(collect(_usage(), now=NOW, history=history))
    charts = [ET.fromstring(svg) for svg in re.findall(r"<svg\b.*?</svg>", source)]
    assert len(charts) == 1
    points = [(float(p.attrib["cx"]), float(p.attrib["cy"])) for p in charts[0].findall("circle")]
    assert points == [(62, 108), (434, 59), (806, 10)]
    lines = charts[0].findall("polyline")
    assert len(lines) == 2  # measured consumption and real reset-derived elapsed time
    ideal = [tuple(map(float, p.split(","))) for p in lines[1].attrib["points"].split()]
    assert ideal[0][1] == pytest.approx(71.2, abs=.1)  # 37.5% of a 120-minute window
    assert [p.text for p in charts[0].findall("text")][-2:] == ["14.08 14:45", "14.08 14:55"]


@pytest.fixture
def fake_card_browser(monkeypatch, tmp_path):
    """Exercise data loading, collection, HTML and delivery; only Chromium is replaced."""
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    import app.charts as charts
    import app.limits_card as card

    captured = []

    class Page:
        def set_default_timeout(self, timeout):
            assert timeout > 0

        async def goto(self, url):
            captured.append(Path(url.removeprefix("file://")).read_text())

        async def screenshot(self, *, path, full_page):
            Path(path).write_bytes(b"synthetic-browser-png")

        async def close(self):
            pass

    browser = SimpleNamespace(is_connected=lambda: True, new_page=AsyncMock(return_value=Page()))
    monkeypatch.setattr(card, "_renderer_loop", None)
    monkeypatch.setattr(card, "_renderer_lock", asyncio.Lock())
    monkeypatch.setattr(card, "_renderer_browser", browser)
    monkeypatch.setattr(charts, "new_chart_path", lambda: tmp_path / "limits.png")
    monkeypatch.setattr(charts, "prune_charts", lambda: None)
    return captured


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_history_reaches_real_card_on_first_delivery_and_saved_refresh(
    monkeypatch, fake_card_browser,
):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    import app.db as db
    import app.routes.system as system
    import app.tg_bridge as tb

    history = _history(*[
        _history_row(ago, grok=[_history_window(value=34)]) for ago in (10, 5)
    ])
    shift = dt.datetime.now(dt.timezone.utc) - NOW
    for row in history["rows"]:
        row["ts"] = (dt.datetime.fromisoformat(row["ts"]) + shift).isoformat()
        window = row["providers"]["grok"]["windows"][0]
        window["resets_at"] = (dt.datetime.fromisoformat(window["resets_at"]) + shift).isoformat()
    read = Mock(return_value=history)
    monkeypatch.setattr(system, "usage_history_data", read)
    monkeypatch.setattr(tb, "_is_limits_owner", AsyncMock(return_value=True))
    monkeypatch.setattr(tb, "_get_limits_usage", AsyncMock(return_value=_usage()))
    sent = AsyncMock(return_value=SimpleNamespace(message_id=901))
    monkeypatch.setattr(tb, "_tg_send_file_safe", sent)
    monkeypatch.setattr(tb, "_tg_send_safe", AsyncMock())
    monkeypatch.setattr(tb, "bot", AsyncMock())
    monkeypatch.setattr(tb, "_live_limits_wake", None)
    state = {}
    monkeypatch.setattr(db, "kv_set", lambda key, value: state.update({key: value}))
    monkeypatch.setattr(db, "kv_get", lambda key: state.get(key, ""))
    await tb.handle_limits(SimpleNamespace(chat=SimpleNamespace(id=123)))
    sent.assert_awaited_once()
    assert sent.await_args.kwargs["is_photo"] is True
    assert json.loads(state[tb._LIVE_LIMITS_KV_KEY])["message_id"] == 901
    assert await tb._refresh_live_limits_message() is True
    tb.bot.edit_message_media.assert_awaited_once()
    assert len(fake_card_browser) == 2
    assert all('<svg ' in source for source in fake_card_browser)
    assert read.call_count == 2
    assert all(call.args == (168,) for call in read.call_args_list)
    tb._tg_send_safe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(10)
@pytest.mark.parametrize("failure", ["exception", "timeout"])
async def test_history_failure_is_bounded_and_still_renders_card(
    monkeypatch, fake_card_browser, failure,
):
    import asyncio
    import app.limits_card as card
    import app.routes.system as system

    if failure == "exception":
        def unavailable(*args):
            raise RuntimeError("synthetic history failure")
        monkeypatch.setattr(system, "usage_history_data", unavailable)
    else:
        monkeypatch.setattr(card, "HISTORY_TIMEOUT_SECONDS", .01)
        async def blocked(*args):
            await asyncio.Event().wait()
        monkeypatch.setattr(asyncio, "to_thread", blocked)
    path = await asyncio.wait_for(card.render_limits_card(_usage(), now=NOW), 2)
    assert path.endswith("limits.png")
    assert len(fake_card_browser) == 1
    assert '<svg ' not in fake_card_browser[0]


@pytest.mark.parametrize("drift, expected_count", [(60, 4), (61, 2)])
def test_history_reset_drift_matches_frontend_one_hour_tolerance(drift, expected_count):
    from app.limits_card import collect_history

    rows = [_history_row(ago, grok=[_history_window(
        reset=_iso(60 if ago > 10 else 60 + drift),
    )]) for ago in (20, 15, 10, 5)]
    result = collect_history(_history(*rows), NOW)[("grok", "primary")]
    assert sum(map(len, result["segments"])) == expected_count


def test_history_ignores_future_and_out_of_range_samples():
    from app.limits_card import collect_history

    rows = [_history_row(ago, grok=[_history_window()]) for ago in (-5, 168 * 60 + 1)]
    assert collect_history(_history(*rows), NOW) == {}


def test_history_uses_instants_with_mixed_timezone_offsets():
    from app.limits_card import collect_history

    rows = [_history_row(ago, grok=[_history_window()]) for ago in (10, 5)]
    rows[0]["ts"] = dt.datetime.fromisoformat(rows[0]["ts"]).astimezone(
        dt.timezone(dt.timedelta(hours=7)),
    ).isoformat()
    result = collect_history(_history(*reversed(rows)), NOW)[("grok", "primary")]
    assert result["end"] - result["start"] == dt.timedelta(minutes=5)
    assert len(result["segments"][0]) == 2


def test_history_without_reset_has_usage_but_no_fabricated_elapsed_line():
    import re
    import xml.etree.ElementTree as ET

    rows = [_history_row(ago, grok=[_history_window(value=20)]) for ago in (10, 5)]
    for row in rows:
        row["providers"]["grok"]["windows"][0].pop("resets_at")
    source = build_html(collect(_usage(), now=NOW, history=_history(*rows)))
    chart = ET.fromstring(re.search(r"<svg\b.*?</svg>", source).group())
    assert len(chart.findall("circle")) == 2
    assert len(chart.findall("polyline")) == 1
