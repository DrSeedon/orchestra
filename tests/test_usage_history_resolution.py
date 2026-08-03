"""Разрешение истории квот: сколько точек отдаём и что делаем с провалами.

Год в 5-минутной сетке — 4.32 МБ (замер 03.08 на живой БД), а график рисует
одно окно лимита в 252 px. Прореживание обязано резать объём, не рисуя линию
там, где снимков не было: в истории регулярны провалы по 5-9 часов.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.routes import system


def _seed(db_path, moments):
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, 10, 20, '', '', 0, 0, '')""",
            [(moment.isoformat(),) for moment in moments],
        )


def _every(start, end, minutes):
    moment = start
    while moment <= end:
        yield moment
        moment += timedelta(minutes=minutes)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "usage.db"
    monkeypatch.setattr("app.db.DB_PATH", path)
    from app.db import init_db

    init_db()
    return path


def test_grid_does_not_bridge_a_hole_in_snapshots(db):
    """Forward-fill рисовал ровную линию через ночь без снимков — это ложь."""
    from app.db import usage_get_history

    now = datetime.now(timezone.utc)
    _seed(db, [
        *_every(now - timedelta(hours=6), now - timedelta(hours=4), 5),
        *_every(now - timedelta(hours=1), now, 5),
    ])

    grid = [datetime.fromisoformat(row["ts"]) for row in usage_get_history(24, 5)]

    hole = [ts for ts in grid
            if now - timedelta(hours=3, minutes=45) < ts < now - timedelta(hours=1, minutes=5)]
    assert not hole, f"в провале выдано {len(hole)} точек"
    assert grid[-1] >= now - timedelta(minutes=5), "свежий хвост потерян"


def test_hole_shorter_than_two_steps_is_still_filled(db):
    """Один пропущенный снимок — не провал: сетка обязана остаться ровной."""
    from app.db import usage_get_history

    now = datetime.now(timezone.utc)
    moments = list(_every(now - timedelta(hours=2), now, 5))
    del moments[10]
    _seed(db, moments)

    grid = usage_get_history(24, 5)
    steps = {
        round((datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds() / 60)
        for a, b in zip(grid, grid[1:])
    }

    assert steps <= {5}, steps


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)


@pytest.mark.asyncio
async def test_short_range_keeps_full_resolution(db, owner):
    now = datetime.now(timezone.utc)
    _seed(db, _every(now - timedelta(hours=6), now, 5))

    answer = await system.usage_history(hours=24)

    assert answer["step_minutes"] == 5
    assert len(answer["rows"]) > 60


@pytest.mark.asyncio
async def test_long_range_is_thinned_but_keeps_a_fine_tail(db, owner):
    """Прореженный год — и полное разрешение там, где принимают решения."""
    now = datetime.now(timezone.utc)
    _seed(db, _every(now - timedelta(days=6), now, 5))

    answer = await system.usage_history(hours=8760)
    rows = answer["rows"]
    spacing = [
        round((datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds() / 60)
        for a, b in zip(rows, rows[1:])
    ]

    assert answer["step_minutes"] == 30
    assert spacing[0] == 30, "старая часть не прорежена"
    assert spacing[-1] == 5, "свежий хвост потерял разрешение"
    # 6 суток в 5-минутной сетке — 1728 точек; прореженные 4 суток + хвост меньше
    assert len(rows) < 1000, f"прореживание не сократило ответ: {len(rows)} точек"


@pytest.mark.asyncio
async def test_chunks_join_without_overlap(db, owner):
    """Кусок по клику ◀ примыкает к загруженному, а не дублирует его границу."""
    now = datetime.now(timezone.utc)
    _seed(db, _every(now - timedelta(days=12), now, 5))

    first = await system.usage_history(hours=168)
    second = await system.usage_history(hours=168, until=first["rows"][0]["ts"])

    assert second["rows"], "предыдущий период пуст — стрелка ◀ упрётся в пустоту"
    assert second["rows"][-1]["ts"] < first["rows"][0]["ts"]


@pytest.mark.asyncio
async def test_navigation_window_anchors_to_data_not_calendar(db, owner):
    """После простоя длиннее окна календарный кусок пришёл бы пустым, и ◀ умерла бы."""
    now = datetime.now(timezone.utc)
    _seed(db, [
        *_every(now - timedelta(days=40), now - timedelta(days=39), 5),
        *_every(now - timedelta(days=2), now, 5),
    ])

    live = await system.usage_history(hours=168)
    older = await system.usage_history(hours=168, until=live["rows"][0]["ts"])

    assert older["rows"], "кусок пуст: окно считалось по календарю, а не по данным"
    assert older["rows"][-1]["ts"] <= (now - timedelta(days=39)).isoformat(), "кусок не из старого блока"


@pytest.mark.asyncio
async def test_historical_chunk_has_no_fine_tail(db, owner):
    """«Последние 48 часов» внутри куска из прошлого — такое же прошлое."""
    now = datetime.now(timezone.utc)
    _seed(db, _every(now - timedelta(days=12), now, 5))

    first = await system.usage_history(hours=168)
    older = await system.usage_history(hours=168, until=first["rows"][0]["ts"])
    rows = older["rows"]
    spacing = {
        round((datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds() / 60)
        for a, b in zip(rows, rows[1:])
    }

    assert spacing == {30}, spacing


@pytest.mark.asyncio
async def test_oldest_ts_is_the_first_snapshot_ever(db, owner):
    """По нему фронт понимает, что за пределами загруженного куска ещё есть история."""
    now = datetime.now(timezone.utc)
    first_moment = now - timedelta(days=40)
    _seed(db, [first_moment, *_every(now - timedelta(days=2), now, 5)])

    answer = await system.usage_history(hours=168)

    assert answer["oldest_ts"] == first_moment.isoformat()
    assert answer["rows"][0]["ts"] > answer["oldest_ts"], "иначе стрелка ◀ не появится"


@pytest.mark.asyncio
async def test_explicit_step_is_honoured(db, owner):
    now = datetime.now(timezone.utc)
    _seed(db, _every(now - timedelta(hours=6), now, 5))

    answer = await system.usage_history(hours=24, step_minutes=60)

    assert answer["step_minutes"] == 60
    assert len(answer["rows"]) <= 8
