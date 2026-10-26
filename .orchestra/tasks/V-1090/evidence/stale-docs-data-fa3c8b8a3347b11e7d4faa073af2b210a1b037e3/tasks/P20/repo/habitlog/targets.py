"""Weekly targets per habit.

The targets file is a CSV file with the columns habit,per_week, for example
"run,3": the habit should be done on at least 3 days of every week.
"""

import csv
from typing import NamedTuple

from habitlog.entries import normalize_habit

TARGET_COLUMNS = ("habit", "per_week")


class Target(NamedTuple):
    """The number of days per week on which a habit should be done."""

    habit: str
    per_week: int


def parse_target(habit: str, per_week: str) -> Target:
    """Make a target from the two fields of a row of the targets file.

    Raises ValueError when the habit name is empty or per_week is not a whole
    number from 1 to 7.
    """
    name = normalize_habit(habit)
    if not name:
        raise ValueError("missing habit name")
    count = per_week.strip()
    if not count.isdigit() or not 1 <= int(count) <= 7:
        raise ValueError(f"per_week must be a whole number from 1 to 7, not {per_week!r}")
    return Target(name, int(count))


def load_targets(path: str) -> list[Target]:
    """Read the targets file, sorted by habit name.

    Raises ValueError when a column is missing, a row is not valid or a habit
    is listed twice.
    """
    targets: dict[str, Target] = {}
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(TARGET_COLUMNS) <= set(reader.fieldnames):
            raise ValueError(f"{path}: expected the columns {','.join(TARGET_COLUMNS)}")
        for row in reader:
            try:
                target = parse_target(row["habit"] or "", row["per_week"] or "")
            except ValueError as err:
                raise ValueError(f"{path}:{reader.line_num}: {err}") from None
            if target.habit in targets:
                raise ValueError(f"{path}:{reader.line_num}: habit {target.habit!r} is listed twice")
            targets[target.habit] = target
    return [targets[name] for name in sorted(targets)]
