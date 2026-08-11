"""Сколько рабочих часов оплачивает остаток недельной квоты Anthropic (#186).

Процент сам по себе решения не даёт: неделя 21.07 дошла до 89 % без последствий, а неделя
04.08 упёрлась в стену на 100 % за двое суток до сброса. Решает отношение остатка к тому,
сколько его ещё предстоит тратить, — отсюда `deficit`: рабочие часы, которые мы потеряем,
если не сбавить темп.

Модуль ничего не решает и ни с чем не сравнивает: порог принадлежит потребителю (у
уведомителя свой, у роутера #187 свой). Здесь только измерение и `DEFAULT_ALERT_DEFICIT_HOURS`
как рекомендованное значение с обоснованием.

Замеры, на которых стоят константы, — `docs/tasks/186/research.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Рабочий час = 06:00–20:00 МСК. В эти 14 часов идёт 97 % расхода: ночью 0.00–0.14 pp/ч
# против 1.0–1.9 в пик (профиль по часам, research.md → Q3). Считать по календарным
# часам нельзя — `deficit` уедет вдвое.
WORK_HOURS_UTC = (3, 17)

# Раньше этого темп — шум: разброс активного часа от 0 до 7 pp при медиане 2.
# 10, а не 6: на шести рабочих часах единственная спокойная неделя в истории (28.07, час 6)
# даёт deficit 15.7 — ложную тревогу. С 8 часов ложных нет, максимум спокойной недели 12.9
# против порога 14. Взято 10, потому что бэктест, породивший сам порог 14, оценивал с 12-го
# КАЛЕНДАРНОГО часа окна = ровно 10 рабочих; применять порог раньше — применять его вне
# диапазона, на котором он проверен. Аварии при этом ловятся всё так же в первые сутки
# (часы 10 и 11 из двух аварийных недель).
# Честно про силу этого обоснования: спокойных недель в истории ВСЕГО ДВЕ, обе с другого
# тарифа, и значение выбрано после того, как я увидел результат. Это граница применимости
# имеющегося бэктеста, а НЕ подтверждённый оптимум. Пересмотреть после первой спокойной
# недели на Max 20 — до неё их не существует вовсе.
MIN_WORK_HOURS_FOR_PACE = 10.0

# Норматив: 100 pp на ~98 рабочих часов недели. Это АЛЛОКАЦИЯ (бюджет ÷ часы), а не
# измеренная пропускная способность — реальный спрос в 1.55 раза выше.
SUSTAINABLE_PACE_PP_PER_WORK_HOUR = 100.0 / 98.0

# Рекомендация, НЕ порог этого модуля: 14 рабочих часов = один потерянный рабочий день.
# Проверено как детектор аварии (сработал в 2 авариях из 2, полоса 14…55 в данных пуста).
# Как признак безопасности НЕ проверен: недель без стены на Max 20 в истории нет вовсе.
DEFAULT_ALERT_DEFICIT_HOURS = 14.0

_WEEKLY_RESET_WEEKDAY = 1  # вторник; 6 сбросов из 6 за 38 суток, ни одного исключения
_WEEKLY_RESET_HOUR = 7     # 07:00 UTC = 10:00 МСК


@dataclass(frozen=True)
class RunwayVerdict:
    """Измерение, а не решение. Сравнение с порогом делает потребитель."""

    state: str                      # "data" | "no_data"
    deficit: float | None           # рабочих часов, которые потеряем; >0 = упрёмся раньше сброса
    pace: float | None              # pp недельной квоты за рабочий час
    runway_hours: float | None      # рабочих часов, оплаченных остатком
    work_hours_left: float | None   # рабочих часов до сброса
    window_id: str                  # личность недельного окна, устойчивая к дрожанию resets_at
    window_end: str                 # момент сброса, ISO
    reason: str


def _as_utc(value: datetime, name: str) -> datetime:
    """Привести к UTC; наивный datetime — ошибка, а не догадка о таймзоне.

    Вся календарная арифметика ниже (полоса суток, вторник 07:00) осмысленна только в UTC.
    Без нормализации `replace(hour=7)` вернул бы вторник 07:00 ПО ЧАСОВОМУ ПОЯСУ ВХОДА, а
    полоса 03:00–17:00 применилась бы к локальным часам — то есть тихо к другим суткам.
    Наивное значение не отклонить нельзя: `astimezone()` истолковал бы его по таймзоне
    машины, и один и тот же вход дал бы разный ответ на разных серверах.
    """
    if value.tzinfo is None:
        raise ValueError(f"{name}: наивный datetime, таймзона обязательна")
    return value.astimezone(timezone.utc)


def _checked_pct(value: float, name: str) -> float:
    """Процент обязан быть конечным числом в 0..100.

    `json.loads` по умолчанию принимает `NaN`, поэтому нечисло может приехать прямо из
    ответа провайдера. `NaN` опасен молчанием: любое сравнение с ним ложно, поэтому он
    проскочил бы все проверки ниже и вернулся бы как `deficit=nan` — вердикт, который
    нельзя ни сравнить с порогом, ни сериализовать.
    """
    if not math.isfinite(value):
        raise ValueError(f"{name}: не конечное число ({value!r})")
    if not 0.0 <= value <= 100.0:
        raise ValueError(f"{name}: {value!r} вне диапазона 0..100")
    return float(value)


def next_weekly_reset(now: datetime) -> datetime:
    """Ближайший вторник 07:00 UTC строго после `now`.

    Fallback, а не основной источник: живой `resets_at` из ответа API главнее. Шесть
    наблюдений не доказывают, что Anthropic никогда не сдвинет якорь, — но когда
    `resets_at` отсутствует (381 снимок из 8804, а 10.08 — 191 подряд), считать по
    календарю лучше, чем не считать вовсе.
    """
    now = _as_utc(now, "now")
    candidate = now.replace(hour=_WEEKLY_RESET_HOUR, minute=0, second=0, microsecond=0)
    days_ahead = (_WEEKLY_RESET_WEEKDAY - candidate.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def window_id_for(reset_at: datetime) -> str:
    """Личность окна = момент сброса, округлённый до минуты.

    `resets_at` мы вычисляем сами как «сейчас + остаток», а не получаем абсолютным, поэтому
    одно и то же окно записано в истории двумя значениями: `…T06:59:59` и `…T07:00:00`
    (например, окно 11.08 встречается 734 и 925 раз соответственно). Латч на сыром значении
    сбрасывался бы примерно каждый второй опрос.
    """
    reset_at = _as_utc(reset_at, "reset_at")
    rounded = (reset_at + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return rounded.isoformat()


def working_hours_between(start: datetime, end: datetime) -> float:
    """Часы из интервала [start, end), попадающие в рабочую полосу суток."""
    start, end = _as_utc(start, "start"), _as_utc(end, "end")
    if end <= start:
        return 0.0
    total = 0.0
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        lo = day.replace(hour=WORK_HOURS_UTC[0])
        hi = day.replace(hour=WORK_HOURS_UTC[1])
        a, b = max(lo, start), min(hi, end)
        if b > a:
            total += (b - a).total_seconds() / 3600.0
        day += timedelta(days=1)
    return total


def _no_data(reason: str, window_id: str, window_end: str) -> RunwayVerdict:
    return RunwayVerdict(
        state="no_data", deficit=None, pace=None, runway_hours=None,
        work_hours_left=None, window_id=window_id, window_end=window_end, reason=reason,
    )


def weekly_runway(
    *,
    utilization: float | None,
    window_start_pct: float | None,
    window_start_at: datetime | None,
    now: datetime,
    reset_at: datetime | None,
) -> RunwayVerdict:
    """Оценить, хватит ли остатка недельной квоты до сброса при текущем темпе.

    `window_start_pct` / `window_start_at` — начало ПОСЛЕДНЕГО монотонного отрезка окна
    (см. `db.runway_window_start_pct`). Переякоривание после внутринедельного обнуления
    счётчика делает запрос, а не эта функция: она вызывается заново каждые 5 минут и памяти
    не имеет, поэтому «переякорюсь сам» означало бы сдвиг базы на каждом опросе и вечный
    `pace = None`.
    """
    now = _as_utc(now, "now")
    fallback = reset_at is None
    reset = next_weekly_reset(now) if fallback else _as_utc(reset_at, "reset_at")
    window_id = window_id_for(reset)
    window_end = reset.isoformat()
    note = "reset_at отсутствует, календарный fallback" if fallback else ""

    if reset <= now:
        return _no_data("снимок протух: окно уже сменилось", window_id, window_end)
    if utilization is None or window_start_pct is None or window_start_at is None:
        return _no_data("данных о квоте нет", window_id, window_end)

    # Проценты валидируем ДО сравнений: `NaN` прошёл бы каждое из них молча.
    utilization = _checked_pct(utilization, "utilization")
    window_start_pct = _checked_pct(window_start_pct, "window_start_pct")
    window_start_at = _as_utc(window_start_at, "window_start_at")

    if utilization < window_start_pct:
        # Счётчик упал ниже базы — обнуление в середине окна (4 раза за 38 суток).
        # Новую базу обязан выбрать запрос; здесь её взять неоткуда.
        return _no_data(
            f"счётчик {utilization:g}% ниже базы {window_start_pct:g}%: нужна переякоренная база",
            window_id, window_end,
        )

    work_used = working_hours_between(window_start_at, now)
    work_left = working_hours_between(now, reset)

    if work_used < MIN_WORK_HOURS_FOR_PACE:
        return RunwayVerdict(
            state="data", deficit=None, pace=None, runway_hours=None,
            work_hours_left=work_left, window_id=window_id, window_end=window_end,
            reason=_join(note, f"рабочих часов в окне {work_used:.1f} — темп не считается"),
        )

    pace = (utilization - window_start_pct) / work_used
    remaining = 100.0 - utilization
    runway = math.inf if pace == 0 else remaining / pace
    deficit = work_left - runway
    return RunwayVerdict(
        state="data", deficit=deficit, pace=pace, runway_hours=runway,
        work_hours_left=work_left, window_id=window_id, window_end=window_end,
        reason=_join(note, f"темп {pace:.2f} pp/раб.ч при нормативе "
                           f"{SUSTAINABLE_PACE_PP_PER_WORK_HOUR:.2f}"),
    )


def _join(note: str, text: str) -> str:
    return f"{note}; {text}" if note else text
