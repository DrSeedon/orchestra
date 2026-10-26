"""Entries of the habit log.

The log is a UTF-8 text file with one entry per line: a day and the name of
a habit done on that day, for example "2024-05-01 run". Blank lines and
lines that start with # are skipped.
"""

from datetime import date
from typing import NamedTuple, Optional

from habitlog.dates import parse_day


class Entry(NamedTuple):
    """One line of the habit log: a habit done on a day."""

    day: date
    habit: str


def normalize_habit(name: str) -> str:
    """A habit name in lower case, with single spaces between words."""
    return " ".join(name.split()).lower()


def parse_line(line: str) -> Optional[Entry]:
    """Parse one log line.

    Returns None for a blank line or a comment line. Raises ValueError when
    the day is not valid or the habit name is missing.
    """
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    day_text, _, name = text.partition(" ")
    habit = normalize_habit(name)
    if not habit:
        raise ValueError(f"missing habit name in {text!r}")
    return Entry(parse_day(day_text), habit)


def read_log(path: str) -> list[Entry]:
    """Read all entries of a log file, in file order.

    Raises ValueError with the file name and the line number when a line is
    not valid.
    """
    entries: list[Entry] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                entry = parse_line(line)
            except ValueError as err:
                raise ValueError(f"{path}:{line_no}: {err}") from None
            if entry is not None:
                entries.append(entry)
    return entries
