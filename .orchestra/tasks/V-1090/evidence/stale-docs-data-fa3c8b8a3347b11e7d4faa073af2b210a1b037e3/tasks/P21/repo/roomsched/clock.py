"""Parse and format the clock times and days used in room and booking files."""
from datetime import date


def parse_time(text: str) -> tuple[int | None, str | None]:
    """Turn a clock time such as ``09:30`` into minutes after midnight.

    :param text: the time as ``HH:MM`` in 24-hour form; ``24:00`` is the end of the day.
    :returns: ``(minutes, None)`` for a valid time, ``(None, message)`` otherwise.
    """
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(len(part) == 2 and part.isdigit() for part in parts):
        return None, f"not a time: {text!r}"
    hours, minutes = int(parts[0]), int(parts[1])
    if minutes > 59 or hours > 24 or (hours == 24 and minutes > 0):
        return None, f"not a time: {text!r}"
    return hours * 60 + minutes, None


def format_time(minutes: int) -> str:
    """Turn minutes after midnight back into ``HH:MM``.

    :param minutes: minutes after midnight, from 0 to 1440.
    :returns: the time as ``HH:MM``.
    """
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_day(text: str) -> tuple[str | None, str | None]:
    """Check a calendar day written as ``YYYY-MM-DD``.

    :param text: the day as written in a file or on the command line.
    :returns: ``(day, None)`` with the day in ISO form, or ``(None, message)``.
    """
    cleaned = text.strip()
    if len(cleaned) != 10:
        return None, f"not a day: {text!r}"
    try:
        day = date.fromisoformat(cleaned)
    except ValueError:
        return None, f"not a day: {text!r}"
    return day.isoformat(), None
