"""Check one week of the habit log against the weekly targets.

Usage: python -m habitlog.weekly LOG TARGETS OUTPUT [--day DAY]

The week runs from Monday to Sunday and contains DAY. Without --day it is the
week of the latest day in the log.
"""

import argparse
import csv
import sys
from datetime import date
from typing import NamedTuple, Optional

from habitlog.dates import parse_day, week_days
from habitlog.entries import Entry, read_log
from habitlog.stats import days_by_habit, entries_between, last_day
from habitlog.targets import Target, load_targets

WEEK_COLUMNS = ("habit", "done", "target", "met")


class WeekRow(NamedTuple):
    """The result of one habit in one week."""

    habit: str
    done: int
    target: int

    @property
    def met(self) -> bool:
        """True when the habit was done on at least as many days as its target."""
        return self.done >= self.target


def week_rows(entries: list[Entry], targets: list[Target], day: date) -> list[WeekRow]:
    """Count the days on which each habit with a target was done in the week of day."""
    days = week_days(day)
    done = days_by_habit(entries_between(entries, days[0], days[-1]))
    return [WeekRow(target.habit, len(done.get(target.habit, [])), target.per_week)
            for target in targets]


def write_rows(path: str, rows: list[WeekRow]) -> None:
    """Write the rows as CSV with the columns habit,done,target,met."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(WEEK_COLUMNS)
        for row in rows:
            writer.writerow([row.habit, row.done, row.target, "yes" if row.met else "no"])


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m habitlog.weekly",
                                     description="Check one week against the weekly targets.")
    parser.add_argument("log", help="habit log file")
    parser.add_argument("targets", help="CSV targets file (habit,per_week)")
    parser.add_argument("output", help="CSV file to write")
    parser.add_argument("--day", help="a day of the week to check, YYYY-MM-DD")
    args = parser.parse_args(argv)

    try:
        entries = read_log(args.log)
        targets = load_targets(args.targets)
        day = parse_day(args.day) if args.day is not None else last_day(entries)
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if day is None:
        print(f"error: {args.log} has no entries and no --day was given", file=sys.stderr)
        return 2
    rows = week_rows(entries, targets, day)
    write_rows(args.output, rows)
    met = sum(1 for row in rows if row.met)
    print(f"week of {week_days(day)[0]}: {met} of {len(rows)} targets met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
