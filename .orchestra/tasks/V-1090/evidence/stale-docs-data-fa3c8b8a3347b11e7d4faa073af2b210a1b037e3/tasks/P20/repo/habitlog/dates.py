"""Calendar days as they are written in the habit log."""

import re
from datetime import date, timedelta

DAY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_day(text: str) -> date:
    """Parse a day written as YYYY-MM-DD.

    Raises ValueError when the text is not a valid day in that form.
    """
    text = text.strip()
    if not DAY_PATTERN.fullmatch(text):
        raise ValueError(f"invalid day {text!r}, expected YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"invalid day {text!r}, expected YYYY-MM-DD") from None


def week_start(day: date) -> date:
    """The Monday of the week of a day."""
    return day - timedelta(days=day.weekday())


def week_days(day: date) -> list[date]:
    """The seven days, Monday to Sunday, of the week of a day."""
    start = week_start(day)
    return [start + timedelta(days=offset) for offset in range(7)]
