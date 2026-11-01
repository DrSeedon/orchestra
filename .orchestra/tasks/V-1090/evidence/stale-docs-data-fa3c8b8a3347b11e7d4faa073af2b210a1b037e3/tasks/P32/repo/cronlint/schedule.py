"""A parsed cron schedule and the times at which it runs."""
from datetime import date, datetime, timedelta
from typing import Optional

from cronlint.fields import DAY, HOUR, MINUTE, MONTH, WEEKDAY, all_values

DEFAULT_SEARCH_DAYS = 366 * 8


class Schedule:
    """The set of values that each field of a cron expression matches.

    ``day_star`` and ``weekday_star`` record whether the day-of-month and
    day-of-week fields start with ``*``. As in cron, when both fields are
    restricted a day matches if either field matches; otherwise both must.
    """

    def __init__(self, expression: str, values: dict[str, frozenset[int]],
                 day_star: bool = True, weekday_star: bool = True) -> None:
        self.expression = expression
        self.values = values
        self.day_star = day_star
        self.weekday_star = weekday_star

    def __repr__(self) -> str:
        return f"Schedule({self.expression!r})"

    def is_full(self, field: str) -> bool:
        """Return True when ``field`` matches every value it allows."""
        return self.values[field] == all_values(field)

    def times(self) -> list[tuple[int, int]]:
        """Return the (hour, minute) pairs of a run day, earliest first."""
        return [(hour, minute) for hour in sorted(self.values[HOUR])
                for minute in sorted(self.values[MINUTE])]

    def matches_day(self, day: date) -> bool:
        """Return True when the schedule runs at some time on ``day``."""
        if day.month not in self.values[MONTH]:
            return False
        in_month = day.day in self.values[DAY]
        in_week = day.isoweekday() % 7 in self.values[WEEKDAY]
        if self.day_star or self.weekday_star:
            return in_month and in_week
        return in_month or in_week

    def matches(self, when: datetime) -> bool:
        """Return True when the schedule runs at the minute ``when``."""
        return (when.minute in self.values[MINUTE] and when.hour in self.values[HOUR]
                and self.matches_day(when.date()))

    def next_run(self, start: datetime,
                 max_days: int = DEFAULT_SEARCH_DAYS) -> Optional[datetime]:
        """Return the first run at or after ``start`` (seconds are ignored).

        Returns None when there is no run in the next ``max_days`` days.
        """
        start = start.replace(second=0, microsecond=0)
        day = start.date()
        for _ in range(max_days):
            if self.matches_day(day):
                for hour, minute in self.times():
                    when = datetime(day.year, day.month, day.day, hour, minute)
                    if when >= start:
                        return when
            day += timedelta(days=1)
        return None

    def runs(self, start: datetime, count: int) -> list[datetime]:
        """Return up to ``count`` runs at or after ``start``, earliest first."""
        found = []
        when = start
        while len(found) < count:
            run = self.next_run(when)
            if run is None:
                break
            found.append(run)
            when = run + timedelta(minutes=1)
        return found
