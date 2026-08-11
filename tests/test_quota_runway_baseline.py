"""База недельного окна для расчёта темпа (#186, тикет T2).

Главная проверка здесь — не «функция вернула число», а то, что после внутринедельного
обнуления счётчика предупреждение продолжает работать на ВСЕХ последующих опросах.
Одиночная оценка в момент падения этот дефект не ловит.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.quota_runway import MIN_WORK_HOURS_FOR_PACE, weekly_runway


RESET = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc)
WINDOW_START = RESET - timedelta(days=7)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db

    init_db()
    return tmp_path / "test.db"


def _write(db, rows):
    """rows: (сдвиг_от_начала_окна, seven_day_pct, seven_day_resets_at).

    `pct=None` → NULL (источник молчал). `resets_at=""` → артефакт #150.
    """
    conn = sqlite3.connect(str(db))
    for offset, pct, resets in rows:
        conn.execute(
            "INSERT INTO usage_snapshots (ts, five_hour_pct, seven_day_pct,"
            " five_hour_resets_at, seven_day_resets_at, total_cost_usd, active_agents)"
            " VALUES (?, ?, ?, ?, ?, 0, 0)",
            ((WINDOW_START + offset).isoformat(), 0.0, pct, "", resets),
        )
    conn.commit()
    conn.close()


def _hours(n: float) -> timedelta:
    return timedelta(hours=n)


def _base(db):
    from app.db import runway_window_start_pct

    return runway_window_start_pct(RESET)


# --- AC-1..AC-3: что считается пригодным снимком --------------------------------------

def test_no_snapshots_in_window_is_none(db):
    assert _base(db) is None


def test_takes_the_first_available_snapshot_when_the_window_starts_with_a_hole(db):
    """Сборщик молчал 191 снимок подряд 10.08 — опора на конкретную точку сломалась бы."""
    _write(db, [(_hours(9), 12.0, RESET.isoformat()), (_hours(11), 15.0, RESET.isoformat())])
    pct, ts = _base(db)
    assert pct == 12.0
    assert ts == (WINDOW_START + _hours(9)).isoformat()


def test_null_percent_rows_are_ignored(db):
    _write(db, [
        (_hours(1), None, RESET.isoformat()),
        (_hours(2), 7.0, RESET.isoformat()),
    ])
    assert _base(db)[0] == 7.0


def test_artifact_rows_without_resets_at_are_ignored(db):
    """Артефакт #150: записанный ноль вместо «источник молчал». Их 70 за историю."""
    _write(db, [
        (_hours(1), 0.0, ""),
        (_hours(2), 6.0, RESET.isoformat()),
    ])
    pct, ts = _base(db)
    assert pct == 6.0
    assert ts == (WINDOW_START + _hours(2)).isoformat()


# --- AC-4: честный ноль — законная база ----------------------------------------------

def test_honest_zero_at_window_start_is_kept_as_baseline(db):
    """Свежее окно закономерно начинается с нуля.

    Отбросив его, база уехала бы на 3 % и занизила темп именно во вторник утром — там,
    где принимается решение о неделе.
    """
    _write(db, [
        (_hours(0), 0.0, RESET.isoformat()),
        (_hours(2), 3.0, RESET.isoformat()),
        (_hours(4), 9.0, RESET.isoformat()),
    ])
    pct, ts = _base(db)
    assert pct == 0.0
    assert ts == WINDOW_START.isoformat()


# --- AC-5, AC-6: переякоривание на последний монотонный отрезок ------------------------

def test_baseline_moves_to_the_last_monotonic_segment(db):
    _write(db, [
        (_hours(0), 2.0, RESET.isoformat()),
        (_hours(10), 40.0, RESET.isoformat()),
        (_hours(20), 60.0, RESET.isoformat()),
        (_hours(21), 1.0, RESET.isoformat()),   # обнуление учёта
        (_hours(24), 4.0, RESET.isoformat()),
    ])
    pct, ts = _base(db)
    assert pct == 1.0
    assert ts == (WINDOW_START + _hours(21)).isoformat()


def test_two_resets_in_one_window_take_the_latest(db):
    _write(db, [
        (_hours(0), 2.0, RESET.isoformat()),
        (_hours(10), 50.0, RESET.isoformat()),
        (_hours(11), 0.0, RESET.isoformat()),
        (_hours(20), 30.0, RESET.isoformat()),
        (_hours(21), 3.0, RESET.isoformat()),
        (_hours(30), 8.0, RESET.isoformat()),
    ])
    assert _base(db) == (3.0, (WINDOW_START + _hours(21)).isoformat())


@pytest.mark.parametrize("drop_to", [59.0, 56.5, 55.1])
def test_small_dips_below_the_measured_threshold_do_not_re_anchor(db, drop_to):
    """За 38 суток счётчик не падал НИ РАЗУ меньше чем на 21 pp.

    Порог 5 pp стоит в пустой полосе; всё, что мельче, — не событие.
    """
    _write(db, [
        (_hours(0), 4.0, RESET.isoformat()),
        (_hours(10), 60.0, RESET.isoformat()),
        (_hours(11), drop_to, RESET.isoformat()),
    ])
    assert _base(db)[0] == 4.0


def test_drop_at_the_measured_threshold_does_re_anchor(db):
    _write(db, [
        (_hours(0), 4.0, RESET.isoformat()),
        (_hours(10), 60.0, RESET.isoformat()),
        (_hours(11), 55.0, RESET.isoformat()),  # ровно −5 pp
    ])
    assert _base(db)[0] == 55.0


# --- AC-7: главный тест тикета — предупреждение переживает обнуление -------------------

def test_pace_recovers_on_every_poll_after_a_mid_window_reset(db):
    """Прогон ВСЕХ пятиминутных опросов после обнуления, а не одной оценки.

    Дефект, который этот тест стережёт: если базу подставлять в момент оценки, она
    уезжает вперёд на каждом опросе, набранных рабочих часов никогда не хватает, и
    `pace` навсегда остаётся `None` — то есть предупреждение выключено до конца недели.
    """
    rows = [(_hours(0), 4.0, RESET.isoformat())]
    # рост до 60 % за первые сутки
    for i in range(1, 13):
        rows.append((_hours(i), 4.0 + i * 4.5, RESET.isoformat()))
    reset_offset = _hours(13)  # 20:00 UTC — обнуление вечером, худший случай
    rows.append((reset_offset, 0.0, RESET.isoformat()))          # обнуление учёта
    # дальше сутки роста, всё время НИЖЕ прежней базы 60 %
    for i in range(1, 25):
        rows.append((reset_offset + _hours(i), float(i * 1.5), RESET.isoformat()))
    _write(db, rows)

    base_pct, base_ts = _base(db)
    assert base_pct == 0.0, "база обязана переехать на точку обнуления"

    window_start_at = datetime.fromisoformat(base_ts)
    verdicts = []
    for i in range(1, 25):
        now = WINDOW_START + reset_offset + _hours(i)
        verdicts.append(weekly_runway(
            utilization=float(i * 1.5), window_start_pct=base_pct,
            window_start_at=window_start_at, now=now, reset_at=RESET,
        ))

    assert all(v.state == "data" for v in verdicts)
    with_pace = [v for v in verdicts if v.pace is not None]
    assert with_pace, "после обнуления темп не восстановился ни на одном опросе"
    # Обнуление пришлось на вечер, поэтому первые опросы честно молчат: рабочих часов
    # ещё не набралось. Важно, что молчание КОНЕЧНО и темп потом не пропадает снова.
    first_with_pace = verdicts.index(with_pace[0])
    assert all(v.pace is not None for v in verdicts[first_with_pace:]), \
        "темп пропал после того, как один раз появился — база уезжает на каждом опросе"
    assert all(v.pace > 0 for v in with_pace)


def test_cumulative_decline_below_the_baseline_never_deadlocks(db):
    """Спуск мелкими шагами, ни один из которых не дотягивает до порога.

    Попарное сравнение такого спуска не видит вовсе, база остаётся выше текущего
    процента, и `weekly_runway` навсегда отвечает `no_data` — предупреждение выключено
    до конца недели. Стережём это сквозным прогоном, а не только запросом.
    """
    _write(db, [
        (_hours(0), 40.0, RESET.isoformat()),
        (_hours(1), 42.0, RESET.isoformat()),
        (_hours(2), 40.0, RESET.isoformat()),
        (_hours(3), 38.0, RESET.isoformat()),
    ])
    base_pct, base_ts = _base(db)
    assert base_pct <= 38.0, "база выше текущего процента = вечный no_data"

    verdict = weekly_runway(
        utilization=38.0, window_start_pct=base_pct,
        window_start_at=datetime.fromisoformat(base_ts),
        now=WINDOW_START + _hours(3), reset_at=RESET,
    )
    assert verdict.state == "data"


def test_repeated_minimum_takes_the_latest_occurrence(db):
    """Счётчик вернулся на дно — накопление началось заново именно оттуда.

    Первое вхождение растянуло бы знаменатель и занизило темп, то есть заглушило бы
    тревогу молча. Разница на реальных данных мала (0.0–0.6 рабочего часа), но
    направление ошибки выбираем в сторону громкого отказа.
    """
    _write(db, [
        (_hours(0), 0.0, RESET.isoformat()),
        (_hours(4), 4.0, RESET.isoformat()),
        (_hours(5), 0.0, RESET.isoformat()),
        (_hours(9), 10.0, RESET.isoformat()),
    ])
    pct, ts = _base(db)
    assert pct == 0.0
    assert ts == (WINDOW_START + _hours(5)).isoformat(), "взято первое дно вместо последнего"


def test_idle_start_of_window_does_not_dilute_the_pace(db):
    """Ноль держался три опроса подряд — эти часы в знаменатель не идут."""
    _write(db, [
        (_hours(0), 0.0, RESET.isoformat()),
        (_hours(1), 0.0, RESET.isoformat()),
        (_hours(2), 0.0, RESET.isoformat()),
        (_hours(3), 6.0, RESET.isoformat()),
    ])
    assert _base(db)[1] == (WINDOW_START + _hours(2)).isoformat()


def test_baseline_never_exceeds_the_latest_value_on_a_ragged_segment(db):
    """Общее свойство: что бы ни было в окне, база не выше последнего наблюдения."""
    _write(db, [
        (_hours(0), 30.0, RESET.isoformat()),
        (_hours(1), 33.0, RESET.isoformat()),
        (_hours(2), 31.0, RESET.isoformat()),
        (_hours(3), 34.0, RESET.isoformat()),
        (_hours(4), 32.0, RESET.isoformat()),
    ])
    assert _base(db)[0] <= 32.0


def test_rows_sharing_a_timestamp_keep_write_order(db):
    """Порядок записи при совпадающем ts обязан сохраняться.

    Простая пара «60 → 0» это НЕ доказывает: после перехода на минимум отрезка ответ
    там одинаков в обе стороны. Различает только случай, где перестановка меняет саму
    нарезку на отрезки: до пары уже есть точка ниже, и в обратном порядке она
    отрезается раньше времени.
    """
    _write(db, [(_hours(1), 10.0, RESET.isoformat())])
    conn = sqlite3.connect(str(db))
    same_ts = (WINDOW_START + _hours(5)).isoformat()
    for pct in (60.0, 5.0):  # порядок записи: сначала 60, потом обнуление до 5
        conn.execute(
            "INSERT INTO usage_snapshots (ts, five_hour_pct, seven_day_pct,"
            " five_hour_resets_at, seven_day_resets_at, total_cost_usd, active_agents)"
            " VALUES (?, 0, ?, '', ?, 0, 0)",
            (same_ts, pct, RESET.isoformat()),
        )
    conn.commit()
    conn.close()
    _write(db, [(_hours(9), 8.0, RESET.isoformat())])
    # верный порядок: 10, 60, 5, 8 → сброс на 5, отрезок [5, 8], минимум 5
    # обратный:       10, 5, 60, 8 → лишний сброс на 5, затем ещё один на 8 → минимум 8
    assert _base(db)[0] == 5.0


def test_baseline_is_stable_across_repeated_calls(db):
    """База — функция истории, а не момента вызова: два подряд вызова совпадают."""
    _write(db, [
        (_hours(0), 5.0, RESET.isoformat()),
        (_hours(10), 55.0, RESET.isoformat()),
        (_hours(11), 2.0, RESET.isoformat()),
        (_hours(12), 6.0, RESET.isoformat()),
    ])
    assert _base(db) == _base(db)


# --- границы окна ---------------------------------------------------------------------

def test_snapshots_of_the_previous_window_are_not_taken(db):
    _write(db, [
        (-_hours(3), 90.0, (RESET - timedelta(days=7)).isoformat()),
        (_hours(1), 2.0, RESET.isoformat()),
    ])
    assert _base(db)[0] == 2.0


def test_snapshot_exactly_at_the_reset_belongs_to_the_next_window(db):
    _write(db, [(timedelta(days=7), 1.0, RESET.isoformat())])
    assert _base(db) is None


def test_naive_reset_is_rejected(db):
    from app.db import runway_window_start_pct

    with pytest.raises(ValueError, match="наивный"):
        runway_window_start_pct(datetime(2026, 8, 11, 7, 0))


def test_min_work_hours_is_respected_end_to_end(db):
    """База найдена, но рабочих часов мало → темпа нет, и это не ошибка."""
    _write(db, [
        (_hours(0), 0.0, RESET.isoformat()),
        (_hours(1), 5.0, RESET.isoformat()),
    ])
    base_pct, base_ts = _base(db)
    verdict = weekly_runway(
        utilization=5.0, window_start_pct=base_pct,
        window_start_at=datetime.fromisoformat(base_ts),
        now=WINDOW_START + _hours(1), reset_at=RESET,
    )
    assert verdict.state == "data"
    assert verdict.pace is None
    assert MIN_WORK_HOURS_FOR_PACE > 1
