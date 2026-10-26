"""Load station readings from CSV files."""

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

FIELDS = ("station", "time", "temp_c", "humidity", "pressure_hpa")
TIME_FORMAT = "%Y-%m-%dT%H:%M"


@dataclass
class Reading:
    """One row of station data. Missing measurements are None."""

    station: str
    time: datetime
    temp_c: float | None
    humidity: float | None
    pressure_hpa: float | None


def parse_number(text: str) -> float | None:
    """Parse a measurement; an empty cell or ``NA`` means missing."""
    text = text.strip()
    if not text or text.upper() == "NA":
        return None
    return float(text)


def parse_row(row: dict[str, str], line_no: int) -> Reading | None:
    """Turn one CSV row into a reading; a bad row is logged and gives None."""
    try:
        return Reading(
            station=row["station"].strip(),
            time=datetime.strptime(row["time"].strip(), TIME_FORMAT),
            temp_c=parse_number(row["temp_c"]),
            humidity=parse_number(row["humidity"]),
            pressure_hpa=parse_number(row["pressure_hpa"]),
        )
    except (KeyError, ValueError, AttributeError) as exc:
        logger.warning("line %d: skipped bad row (%s)", line_no, exc)
        return None


def load_readings(csv_path: str) -> list[Reading]:
    """Read all good rows of a station CSV file, sorted by station and time."""
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(csv_path)
    readings = []
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [f for f in FIELDS if f not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{os.path.basename(csv_path)}: missing columns {missing}")
        for line_no, row in enumerate(reader, start=2):
            reading = parse_row(row, line_no)
            if reading is not None:
                readings.append(reading)
    logger.info("loaded %d readings from %s", len(readings), csv_path)
    return sorted(readings, key=lambda r: (r.station, r.time))


def by_station(readings: list[Reading]) -> dict[str, list[Reading]]:
    """Group readings by station id, keeping their order."""
    groups: dict[str, list[Reading]] = {}
    for reading in readings:
        groups.setdefault(reading.station, []).append(reading)
    return groups
