"""Selecting entries and counting the days on which habits were done."""

from datetime import date
from typing import Optional

from habitlog.entries import Entry


def entries_between(entries: list[Entry], first: Optional[date] = None,
                    last: Optional[date] = None) -> list[Entry]:
    """The entries from first to last, both days included.

    A bound that is None leaves that side open.
    """
    return [entry for entry in entries
            if (first is None or entry.day >= first) and (last is None or entry.day <= last)]


def days_by_habit(entries: list[Entry]) -> dict[str, list[date]]:
    """The days on which each habit was done, earliest first, keyed by habit name.

    A habit that is logged more than once on a day counts once for that day.
    The habits are in alphabetical order.
    """
    found: dict[str, set[date]] = {}
    for entry in entries:
        found.setdefault(entry.habit, set()).add(entry.day)
    return {habit: sorted(found[habit]) for habit in sorted(found)}


def last_day(entries: list[Entry]) -> Optional[date]:
    """The latest day of the entries, or None when there are no entries."""
    return max((entry.day for entry in entries), default=None)
