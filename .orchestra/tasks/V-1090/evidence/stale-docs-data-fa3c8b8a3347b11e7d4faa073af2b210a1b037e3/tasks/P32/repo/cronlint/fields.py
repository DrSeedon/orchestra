"""The five fields of a cron expression and the values they allow."""
from typing import Optional

MINUTE = "minute"
HOUR = "hour"
DAY = "day"
MONTH = "month"
WEEKDAY = "weekday"

FIELD_ORDER = (MINUTE, HOUR, DAY, MONTH, WEEKDAY)

# Lowest and highest value of each field. Day of week 0 is Sunday; the
# parser also accepts 7 for Sunday and stores it as 0.
BOUNDS = {
    MINUTE: (0, 59),
    HOUR: (0, 23),
    DAY: (1, 31),
    MONTH: (1, 12),
    WEEKDAY: (0, 6),
}

MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
WEEKDAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


def all_values(field: str) -> frozenset[int]:
    """Return every value that ``field`` allows."""
    low, high = BOUNDS[field]
    return frozenset(range(low, high + 1))


def name_value(field: str, token: str) -> Optional[int]:
    """Return the number for a month or weekday name, or None for other tokens."""
    key = token.lower()
    if field == MONTH and key in MONTH_NAMES:
        return MONTH_NAMES.index(key) + 1
    if field == WEEKDAY and key in WEEKDAY_NAMES:
        return WEEKDAY_NAMES.index(key)
    return None
