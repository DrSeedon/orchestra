"""Метрика недельного runway (#186, тикет T1).

Исторический реплей здесь — ВНЕШНЯЯ валидация, а не единственный оракул: четыре недели
проходятся переобучением (реализация может узнать даты). Поэтому основную работу делают
метаморфные свойства и аналитический случай, посчитанный на бумаге.

Ряды вморожены в файл намеренно: тест, читающий живую БД, зелен ровно до следующей записи.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.quota_runway import (
    DEFAULT_ALERT_DEFICIT_HOURS,
    MIN_WORK_HOURS_FOR_PACE,
    RunwayVerdict,
    next_weekly_reset,
    weekly_runway,
    window_id_for,
    working_hours_between,
)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# Часы от сброса → seven_day_pct, из `usage_snapshots` (снимок 11.08.2026).
# Пропущенные часы = снимка нет. Сброс всегда вторник 07:00 UTC.
WEEKS: dict[str, tuple[str, dict[int, int]]] = {
    # обе аварийные недели на Max 20 — обе кончились стеной
    "07.07 Max20": ("2026-07-07T07:00", {
        0: 1, 1: 3, 2: 5, 3: 10, 4: 16, 5: 18, 6: 21, 7: 22, 8: 22, 9: 22, 10: 23, 11: 23,
        12: 23, 20: 24, 21: 25, 22: 26, 23: 26, 24: 29, 25: 30, 26: 33, 27: 34, 29: 36,
        30: 39, 34: 40, 44: 41, 45: 43, 46: 46, 47: 51, 48: 51, 49: 54, 50: 55, 51: 56,
        52: 58, 53: 61, 54: 65, 55: 66, 56: 70, 57: 71, 58: 72,
        # h=68 — внеплановое обнуление счётчика (72 % → 2 %)
        68: 2, 70: 6, 73: 9, 74: 14, 75: 18, 78: 22, 83: 26, 93: 35, 95: 41, 100: 51,
        104: 59, 106: 61, 120: 71, 126: 82, 131: 86, 141: 93, 144: 97, 149: 100, 167: 100,
    }),
    "04.08 Max20": ("2026-08-04T07:00", {
        0: 2, 1: 7, 2: 14, 3: 17, 6: 19, 7: 22, 8: 24, 9: 25, 11: 30, 12: 31, 13: 32,
        23: 33, 24: 33, 27: 34, 28: 38, 29: 40, 30: 45, 31: 48, 32: 49, 33: 50, 44: 51,
        45: 53, 46: 56, 47: 57, 48: 61, 51: 62, 52: 64, 53: 65, 54: 66, 55: 67, 56: 68,
        57: 69, 68: 76, 69: 78, 70: 82, 71: 85, 72: 89, 73: 90, 74: 92, 75: 93, 76: 94,
        77: 95, 90: 96, 95: 97, 100: 98, 104: 99, 120: 100, 147: 100,
    }),
    # недели без стены — обе с ДРУГОГО тарифа, безопасных недель на Max 20 в истории нет
    "21.07 Max5": ("2026-07-21T07:00", {
        0: 1, 1: 2, 4: 3, 5: 8, 9: 10, 10: 11, 20: 12, 23: 13, 24: 13, 25: 14, 30: 15,
        44: 17, 47: 18, 51: 20, 54: 24, 55: 25, 56: 26, 58: 27, 67: 30, 68: 32, 69: 35,
        72: 36, 73: 37, 74: 38, 75: 39, 82: 40, 92: 41, 93: 43, 94: 44, 95: 45, 99: 49,
        100: 52, 102: 54, 103: 56, 104: 57, 107: 58, 117: 59, 119: 61, 120: 63, 121: 64,
        122: 65, 123: 66, 127: 69, 128: 70, 129: 71, 130: 72, 132: 73, 145: 74, 147: 75,
        148: 76, 151: 79, 152: 81, 155: 82, 164: 83, 166: 87, 167: 89,
    }),
    "28.07 Max5→20": ("2026-07-28T07:00", {
        0: 4, 1: 5, 2: 7, 3: 8, 5: 10, 6: 11, 7: 12, 9: 13, 21: 14, 22: 15, 24: 15,
        25: 16, 26: 17, 27: 18, 28: 19, 29: 20, 30: 22, 32: 23, 43: 24, 44: 25, 45: 26,
        46: 27, 47: 28, 48: 29, 50: 33, 51: 35, 53: 37, 54: 39, 55: 41, 68: 44, 69: 48,
        72: 49, 77: 50, 78: 51, 79: 52, 93: 53, 94: 56, 95: 59,
        # h=96 — внеплановое обнуление счётчика (59 % → 4 %), граница тарифа 01.08
        96: 4, 97: 6, 98: 8, 99: 10, 102: 13, 105: 14, 116: 16, 117: 17, 118: 18,
        119: 20, 120: 23, 121: 26, 125: 27, 128: 28, 130: 29, 140: 32, 141: 34, 142: 37,
        143: 38, 144: 41, 145: 45, 146: 50, 147: 52, 148: 55, 150: 58, 152: 61, 153: 65,
        154: 67, 165: 72, 166: 74, 167: 80,
    }),
}

# Замер из research.md → Q4: `D` на 24-м часу окна.
EXPECTED_DEFICIT_AT_H24 = {
    "07.07 Max20": 48.0,
    "04.08 Max20": 54.0,
    "21.07 Max5": -18.0,
    "28.07 Max5→20": -24.0,
}

# Час, на котором обе аварийные недели уже были распознаваемы (вторник 19:00 UTC).
DECISION_HOUR = 12


def _verdict_at(week: str, hour: int) -> RunwayVerdict:
    """Оценка на N-м часу окна с базой на его старте — как в бэктесте ресёрча."""
    start_text, series = WEEKS[week]
    start = _utc(start_text)
    return weekly_runway(
        utilization=float(series[hour]),
        window_start_pct=float(series[0]),
        window_start_at=start,
        now=start + timedelta(hours=hour),
        reset_at=start + timedelta(days=7),
    )


# --- AC-1: реплей четырёх недель воспроизводит замеренные значения -------------------

@pytest.mark.parametrize("week", sorted(EXPECTED_DEFICIT_AT_H24))
def test_replay_reproduces_measured_deficit(week):
    verdict = _verdict_at(week, 24)
    assert verdict.state == "data"
    assert verdict.deficit == pytest.approx(EXPECTED_DEFICIT_AT_H24[week], abs=2.0)


# --- AC-2: порог разделяет аварийные недели и спокойные ------------------------------

@pytest.mark.parametrize("week", ["07.07 Max20", "04.08 Max20"])
def test_incident_weeks_exceed_threshold_on_decision_hour(week):
    assert _verdict_at(week, DECISION_HOUR).deficit > DEFAULT_ALERT_DEFICIT_HOURS


@pytest.mark.parametrize("week", ["21.07 Max5", "28.07 Max5→20"])
def test_calm_weeks_never_exceed_threshold(week):
    """Ни на одном часу окна — не только на решающем.

    До внепланового обнуления счётчика: после него база больше не действительна, и
    переякоривание — работа T2, а не этой функции.
    """
    _, series = WEEKS[week]
    reset_hour = _first_counter_drop(series)
    checked = 0
    for hour in sorted(series):
        if hour == 0 or hour >= reset_hour:
            continue
        verdict = _verdict_at(week, hour)
        if verdict.deficit is None:
            continue
        checked += 1
        assert verdict.deficit <= DEFAULT_ALERT_DEFICIT_HOURS, f"{week}, час {hour}"
    assert checked > 20, "проверено слишком мало часов — фикстура или фильтр сломаны"


def _first_counter_drop(series: dict[int, int]) -> int:
    hours = sorted(series)
    for prev, cur in zip(hours, hours[1:]):
        if series[cur] < series[prev]:
            return cur
    return 10**6


# --- AC-3, AC-4, AC-5: отсутствие данных, короткое окно, нулевой расход ---------------

@pytest.mark.parametrize("missing", ["utilization", "window_start_pct", "window_start_at"])
def test_missing_input_is_no_data_not_zero(missing):
    kwargs = dict(
        utilization=40.0, window_start_pct=5.0,
        window_start_at=_utc("2026-08-04T07:00"),
        now=_utc("2026-08-05T07:00"), reset_at=_utc("2026-08-11T07:00"),
    )
    kwargs[missing] = None
    verdict = weekly_runway(**kwargs)
    assert verdict.state == "no_data"
    assert verdict.deficit is None and verdict.pace is None


def test_short_window_reports_data_without_pace():
    start = _utc("2026-08-04T07:00")
    verdict = weekly_runway(
        utilization=9.0, window_start_pct=2.0, window_start_at=start,
        now=start + timedelta(hours=3), reset_at=start + timedelta(days=7),
    )
    assert verdict.state == "data"
    assert verdict.pace is None and verdict.deficit is None
    assert verdict.work_hours_left is not None


def test_zero_spend_gives_infinite_runway_without_division_error():
    start = _utc("2026-08-04T07:00")
    verdict = weekly_runway(
        utilization=5.0, window_start_pct=5.0, window_start_at=start,
        now=start + timedelta(hours=24), reset_at=start + timedelta(days=7),
    )
    assert verdict.pace == 0
    assert verdict.runway_hours == float("inf")
    assert verdict.deficit < 0


# --- AC-6: календарный fallback ------------------------------------------------------

def test_missing_reset_falls_back_to_next_tuesday_and_says_so():
    now = _utc("2026-08-06T09:00")  # четверг
    verdict = weekly_runway(
        utilization=40.0, window_start_pct=2.0, window_start_at=_utc("2026-08-04T07:00"),
        now=now, reset_at=None,
    )
    assert verdict.window_end.startswith("2026-08-11T07:00")
    assert "fallback" in verdict.reason


def test_next_weekly_reset_is_strictly_in_the_future_on_the_boundary():
    exactly_on_reset = _utc("2026-08-11T07:00")
    assert next_weekly_reset(exactly_on_reset) == _utc("2026-08-18T07:00")


# --- AC-7: window_id устойчив к дрожанию resets_at -----------------------------------

def test_window_id_survives_the_one_second_jitter():
    """В истории каждое окно записано и как …T06:59:59, и как …T07:00:00."""
    early = window_id_for(_utc("2026-08-11T06:59:59.582868"))
    late = window_id_for(_utc("2026-08-11T07:00:00.412001"))
    assert early == late


# --- AC-8: метаморфные свойства (реплей их не заменяет) -------------------------------

def _analytic(pace_pp_per_hour: float, reset_after_calendar_hours: float = 4.0):
    """Окно, собранное так, чтобы ответ считался на бумаге.

    Старт 03:00 UTC — ровно начало рабочей полосы, поэтому первые 14 календарных часов
    рабочие один в один. Оценка на 13:00 → ровно 10 рабочих часов позади.
    """
    start = _utc("2026-08-04T03:00")
    now = start + timedelta(hours=10)                       # 13:00, 10 рабочих часов
    reset = now + timedelta(hours=reset_after_calendar_hours)
    return weekly_runway(
        utilization=pace_pp_per_hour * 10.0, window_start_pct=0.0,
        window_start_at=start, now=now, reset_at=reset,
    )


def test_analytic_case_matches_hand_computation():
    # 10 рабочих часов по 2.0 pp → израсходовано 20 %, остаток 80, runway = 80/2 = 40.
    # Сброс через 4 календарных часа (13:00 → 17:00) = ровно 4 рабочих часа.
    verdict = _analytic(pace_pp_per_hour=2.0, reset_after_calendar_hours=4.0)
    assert verdict.pace == pytest.approx(2.0)
    assert verdict.runway_hours == pytest.approx(40.0)
    assert verdict.work_hours_left == pytest.approx(4.0)
    assert verdict.deficit == pytest.approx(-36.0)


def test_higher_burn_strictly_increases_deficit():
    deficits = [_analytic(p).deficit for p in (1.0, 2.0, 4.0, 8.0)]
    assert deficits == sorted(deficits), deficits
    assert len(set(deficits)) == len(deficits)


@pytest.mark.parametrize("week", sorted(WEEKS))
def test_shifting_everything_by_whole_weeks_changes_nothing_numeric(week):
    """Сдвиг на целое число недель сохраняет и день недели, и рабочую полосу."""
    start_text, series = WEEKS[week]
    start = _utc(start_text)
    hour = 24
    base = _verdict_at(week, hour)
    shifted = weekly_runway(
        utilization=float(series[hour]), window_start_pct=float(series[0]),
        window_start_at=start + timedelta(weeks=3),
        now=start + timedelta(weeks=3, hours=hour),
        reset_at=start + timedelta(weeks=4),
    )
    assert shifted.pace == pytest.approx(base.pace)
    assert shifted.deficit == pytest.approx(base.deficit)
    assert shifted.work_hours_left == pytest.approx(base.work_hours_left)
    assert shifted.window_id != base.window_id  # личность окна обязана быть другой


def test_moving_the_reset_adds_exactly_the_working_hours_it_contains():
    """Сброс отодвинут ровно на сутки → рабочих часов до него ровно на 14 больше."""
    base = _analytic(2.0, reset_after_calendar_hours=4.0)    # сброс 17:00 → 4 рабочих часа
    later = _analytic(2.0, reset_after_calendar_hours=28.0)  # сброс 17:00 назавтра → 18
    assert later.work_hours_left == pytest.approx(base.work_hours_left + 14.0)
    assert later.deficit == pytest.approx(base.deficit + 14.0)


# --- AC-9, AC-10: протухший снимок и счётчик ниже базы --------------------------------

def test_stale_snapshot_after_window_rollover_is_no_data():
    verdict = weekly_runway(
        utilization=90.0, window_start_pct=2.0, window_start_at=_utc("2026-08-04T07:00"),
        now=_utc("2026-08-11T09:00"), reset_at=_utc("2026-08-11T07:00"),
    )
    assert verdict.state == "no_data"
    assert "протух" in verdict.reason


def test_counter_below_baseline_is_no_data_never_negative_pace():
    """Обнуление счётчика в середине окна — 4 раза за 38 суток.

    Переякорить базу может только запрос (T2): эта функция вызывается заново каждые
    5 минут и памяти не имеет.
    """
    start = _utc("2026-07-28T07:00")
    verdict = weekly_runway(
        utilization=4.0, window_start_pct=59.0, window_start_at=start,
        now=start + timedelta(hours=96), reset_at=start + timedelta(days=7),
    )
    assert verdict.state == "no_data"
    assert verdict.pace is None


# --- рабочие часы: арифметика, на которой стоит всё остальное -------------------------

def test_working_hours_skip_the_night():
    full_day = working_hours_between(_utc("2026-08-04T00:00"), _utc("2026-08-05T00:00"))
    assert full_day == pytest.approx(14.0)


def test_working_hours_over_a_full_week():
    week = working_hours_between(_utc("2026-08-04T07:00"), _utc("2026-08-11T07:00"))
    assert week == pytest.approx(98.0)


def test_working_hours_are_zero_for_a_night_only_interval():
    assert working_hours_between(_utc("2026-08-04T18:00"), _utc("2026-08-05T02:00")) == 0.0


def test_working_hours_never_negative_on_reversed_interval():
    assert working_hours_between(_utc("2026-08-05T00:00"), _utc("2026-08-04T00:00")) == 0.0


def test_partial_hours_are_counted_at_minute_resolution():
    """Мутация, которую не ловил ни один прежний тест: усечение дневного пересечения.

    Все остальные проверки стоят на целых границах полосы, поэтому
    `total += int(...)` прошёл бы их насквозь. Здесь минута до 17:00 и минута после
    03:00 обязаны дать ровно 2/60 часа.
    """
    crossing_the_night = working_hours_between(
        _utc("2026-08-04T16:59"), _utc("2026-08-05T03:01"),
    )
    assert crossing_the_night == pytest.approx(2 / 60)


# --- контракт входов: таймзона обязательна, проценты конечны и в 0..100 ---------------

def test_naive_datetime_is_rejected_loudly():
    """Наивное значение `astimezone()` истолковал бы по таймзоне машины."""
    with pytest.raises(ValueError, match="наивный"):
        working_hours_between(datetime(2026, 8, 4, 3, 0), _utc("2026-08-04T17:00"))


def test_non_utc_input_is_normalised_not_taken_literally():
    """Тот же момент времени в UTC+03:00 обязан дать тот же ответ."""
    tz3 = timezone(timedelta(hours=3))
    same_moment = working_hours_between(
        _utc("2026-08-04T03:00").astimezone(tz3),
        _utc("2026-08-04T17:00").astimezone(tz3),
    )
    assert same_moment == pytest.approx(14.0)


def test_weekly_reset_is_seven_utc_regardless_of_input_timezone():
    tz3 = timezone(timedelta(hours=3))
    from_utc = next_weekly_reset(_utc("2026-08-06T09:00"))
    from_tz3 = next_weekly_reset(_utc("2026-08-06T09:00").astimezone(tz3))
    assert from_utc == from_tz3 == _utc("2026-08-11T07:00")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 100.5])
def test_impossible_percentage_raises_instead_of_flowing_through(bad):
    """`NaN` страшнее прочего: любое сравнение с ним ложно, и он прошёл бы все ветки."""
    with pytest.raises(ValueError):
        weekly_runway(
            utilization=bad, window_start_pct=2.0,
            window_start_at=_utc("2026-08-04T03:00"),
            now=_utc("2026-08-04T17:00"), reset_at=_utc("2026-08-11T07:00"),
        )


@pytest.mark.parametrize("bad", [float("nan"), -0.5, 101.0])
def test_impossible_baseline_raises_too(bad):
    with pytest.raises(ValueError):
        weekly_runway(
            utilization=40.0, window_start_pct=bad,
            window_start_at=_utc("2026-08-04T03:00"),
            now=_utc("2026-08-04T17:00"), reset_at=_utc("2026-08-11T07:00"),
        )


def test_infinite_runway_is_the_documented_contract_for_zero_spend():
    """`inf` остаётся во внутреннем контракте — потребитель ОБЯЗАН его форматировать.

    Строгий JSON-кодер такое отвергнет, а наивный запишет нестандартное `Infinity`.
    Тест фиксирует и то, и другое, чтобы T4 не отдал юзеру «упрёмся через inf часов».
    """
    import json
    import math as _math

    start = _utc("2026-08-04T03:00")
    verdict = weekly_runway(
        utilization=5.0, window_start_pct=5.0, window_start_at=start,
        now=start + timedelta(hours=24), reset_at=start + timedelta(days=7),
    )
    assert _math.isinf(verdict.runway_hours) and _math.isinf(verdict.deficit)
    with pytest.raises(ValueError):
        json.dumps({"runway_hours": verdict.runway_hours}, allow_nan=False)


def test_min_work_hours_constant_is_the_one_the_code_uses():
    """Страховка от расхождения теста и модуля, если константу поправят."""
    start = _utc("2026-08-04T03:00")
    just_under = weekly_runway(
        utilization=10.0, window_start_pct=0.0, window_start_at=start,
        now=start + timedelta(hours=MIN_WORK_HOURS_FOR_PACE - 0.5),
        reset_at=start + timedelta(days=7),
    )
    just_over = weekly_runway(
        utilization=10.0, window_start_pct=0.0, window_start_at=start,
        now=start + timedelta(hours=MIN_WORK_HOURS_FOR_PACE + 0.5),
        reset_at=start + timedelta(days=7),
    )
    assert just_under.pace is None
    assert just_over.pace is not None
