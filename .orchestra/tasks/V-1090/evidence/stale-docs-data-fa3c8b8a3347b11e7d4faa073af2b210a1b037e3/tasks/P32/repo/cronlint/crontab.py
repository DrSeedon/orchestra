"""Read crontab files into schedule entries."""
import re
from dataclasses import dataclass

from cronlint.errors import CronSyntaxError

# NAME=value lines set variables for the jobs; they are not schedule entries.
VARIABLE_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")


@dataclass
class CrontabEntry:
    """One schedule line of a crontab file."""

    line: int
    expression: str
    command: str


def split_entry(text: str) -> tuple[str, str]:
    """Split a schedule line into its expression and its command."""
    field_count = 1 if text.startswith("@") else 5
    parts = text.split(None, field_count)
    if len(parts) <= field_count:
        raise CronSyntaxError(f"no command in {text!r}")
    return " ".join(parts[:field_count]), parts[field_count]


def parse_crontab(text: str) -> list[CrontabEntry]:
    """Return the schedule entries of a crontab, in file order.

    Blank lines, ``#`` comment lines and variable lines are skipped but still
    count for line numbers; the first line is line 1.
    """
    entries = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or VARIABLE_LINE.match(stripped):
            continue
        try:
            expression, command = split_entry(stripped)
        except CronSyntaxError as err:
            raise CronSyntaxError(f"line {number}: {err}") from None
        entries.append(CrontabEntry(number, expression, command))
    return entries


def read_crontab(path: str) -> list[CrontabEntry]:
    """Read the crontab file at ``path`` and return its schedule entries."""
    with open(path, encoding="utf-8") as fh:
        return parse_crontab(fh.read())
