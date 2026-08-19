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
    }
    usage.update(over)
    return usage


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
async def test_limits_usage_reads_the_same_source_as_the_route(monkeypatch):
    """`/limits` и `/api/usage` обязаны собирать картинку из ОДНОГО вызова."""
    import app.routes.system as system
    import app.tg_bridge as tb

    raw = {"anthropic": {"five_hour": {"utilization": 4.0}}}
    monkeypatch.setattr(system, "_get_usage_data", AsyncMock(return_value=raw))

    assert await tb._get_limits_usage() == raw


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
    render = AsyncMock(return_value=str(png))
    monkeypatch.setattr(card, "render_limits_card", render)

    response = await system.get_usage_card()

    render.assert_awaited_once_with(raw)
    assert response.path == str(png)
    assert response.media_type == "image/png"
    assert response.filename == "limits.png"
