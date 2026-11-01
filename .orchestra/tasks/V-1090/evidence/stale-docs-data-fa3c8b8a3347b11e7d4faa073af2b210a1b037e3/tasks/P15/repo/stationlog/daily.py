"""Daily summaries per station."""

import logging
from dataclasses import dataclass
from datetime import date

from .readings import Reading, by_station

logger = logging.getLogger(__name__)


@dataclass
class DailySummary:
    """Summary of one station on one day. Values are None if no data."""

    station: str
    day: date
    count: int
    temp_min: float | None
    temp_max: float | None
    temp_mean: float | None
    humidity_mean: float | None


def mean(values: list[float]) -> float | None:
    """Arithmetic mean rounded to 0.1, or None for no values."""
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def summarize_day(station: str, day: date, readings: list[Reading]) -> DailySummary:
    """Summarize the readings of one station on one day."""
    temps = [r.temp_c for r in readings if r.temp_c is not None]
    hums = [r.humidity for r in readings if r.humidity is not None]
    if not temps:
        logger.warning("%s %s: no temperature readings", station, day.isoformat())
    return DailySummary(
        station=station,
        day=day,
        count=len(readings),
        temp_min=min(temps) if temps else None,
        temp_max=max(temps) if temps else None,
        temp_mean=mean(temps),
        humidity_mean=mean(hums),
    )


def daily_summaries(readings: list[Reading]) -> list[DailySummary]:
    """Summaries for every station and day, ordered by station then day."""
    result = []
    for station, rows in sorted(by_station(readings).items()):
        days: dict[date, list[Reading]] = {}
        for row in rows:
            days.setdefault(row.time.date(), []).append(row)
        for day in sorted(days):
            result.append(summarize_day(station, day, days[day]))
    return result
