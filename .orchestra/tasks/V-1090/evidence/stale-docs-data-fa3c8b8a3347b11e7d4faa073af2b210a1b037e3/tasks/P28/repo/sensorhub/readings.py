"""Read sensor readings from a CSV file with the columns time, sensor and value."""
import csv
from dataclasses import dataclass
from datetime import datetime

COLUMNS = ("time", "sensor", "value")


@dataclass(frozen=True)
class Reading:
    """One reading of one sensor."""

    time: datetime
    sensor: str
    value: float


def parse_reading(row: dict[str, str | None]) -> tuple[Reading | None, str | None]:
    """Build a Reading from one CSV row, or return a message that says what is wrong."""
    sensor = (row.get("sensor") or "").strip()
    if not sensor:
        return None, "sensor is empty"
    text = (row.get("time") or "").strip()
    try:
        time = datetime.fromisoformat(text)
    except ValueError:
        return None, f"bad time {text!r}"
    text = (row.get("value") or "").strip()
    try:
        value = float(text)
    except ValueError:
        return None, f"bad value {text!r}"
    return Reading(time=time, sensor=sensor, value=value), None


def load_readings(path: str) -> tuple[list[Reading] | None, str | None]:
    """Read all readings of a file, sorted by time.

    Rows that cannot be read are skipped and reported. A missing file or a missing
    column is an error.
    """
    try:
        handle = open(path, newline="", encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror}"
    readings: list[Reading] = []
    with handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            return None, f"{path}: missing columns {', '.join(missing)}"
        for line_no, row in enumerate(reader, start=2):
            reading, error = parse_reading(row)
            if reading is None:
                print(f"{path}:{line_no}: {error}, row skipped")
                continue
            readings.append(reading)
    readings.sort(key=lambda reading: reading.time)
    return readings, None
