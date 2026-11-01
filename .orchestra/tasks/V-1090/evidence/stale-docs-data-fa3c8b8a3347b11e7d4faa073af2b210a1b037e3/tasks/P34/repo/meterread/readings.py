"""Meter readings from a CSV file with the columns meter, date and kwh."""
import csv
from dataclasses import dataclass
from datetime import date

READING_COLUMNS = ("meter", "date", "kwh")


@dataclass(frozen=True)
class Reading:
    """One reading of a meter: the counter value in whole kWh on a day."""

    meter: str
    day: date
    kwh: int


def parse_row(row: dict[str, str | None]) -> tuple[Reading | None, str | None]:
    """Turn one CSV row into a reading.

    :param row: the row, as read by ``csv.DictReader``
    :returns: the reading and None, or None and an error message
    """
    meter = (row.get("meter") or "").strip()
    if not meter:
        return None, "no meter id"
    day_text = (row.get("date") or "").strip()
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return None, f"bad date {day_text!r}"
    kwh_text = (row.get("kwh") or "").strip()
    if not kwh_text.isdigit():
        return None, f"bad meter value {kwh_text!r}"
    return Reading(meter, day, int(kwh_text)), None


def load_readings(path: str) -> tuple[list[Reading] | None, str | None]:
    """Read all readings of a file, in file order.

    :param path: the CSV file
    :returns: the readings and None, or None and an error message
    """
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if tuple(reader.fieldnames or ()) != READING_COLUMNS:
                return None, f"{path}: the header must be {','.join(READING_COLUMNS)}"
            rows = list(reader)
    except OSError as err:
        return None, f"cannot read {path}: {err.strerror}"
    readings = []
    for number, row in enumerate(rows, start=2):
        reading, error = parse_row(row)
        if error:
            return None, f"{path} line {number}: {error}"
        readings.append(reading)
    return readings, None


def group_by_meter(readings: list[Reading]) -> dict[str, list[Reading]]:
    """Group readings by meter.

    :param readings: readings of any meters, in any order
    :returns: the readings of each meter sorted by day; meters in order of first appearance
    """
    groups: dict[str, list[Reading]] = {}
    for reading in readings:
        groups.setdefault(reading.meter, []).append(reading)
    for items in groups.values():
        items.sort(key=lambda reading: reading.day)
    return groups


def check_meter(readings: list[Reading]) -> str | None:
    """Check the sorted readings of one meter.

    :param readings: the readings of one meter, sorted by day
    :returns: an error message, or None when the readings are fine
    """
    for before, after in zip(readings, readings[1:]):
        if after.day == before.day:
            return f"meter {after.meter}: two readings on {after.day.isoformat()}"
        if after.kwh < before.kwh:
            return f"meter {after.meter}: the reading on {after.day.isoformat()} is lower than the one before"
    return None
