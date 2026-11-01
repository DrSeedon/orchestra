"""Trips of the car pool: who drove which car how far, and who rode along."""
import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

COLUMNS = ("date", "car", "km", "driver", "riders")


@dataclass(frozen=True)
class Trip:
    """One trip. Riders are the people in the car besides the driver, in the order listed."""

    day: date
    car: str
    km: Decimal
    driver: str
    riders: tuple[str, ...]


def parseRiders(text: str) -> list[str]:
    """Split the riders column; names are separated by semicolons and may be empty."""
    return [name.strip() for name in text.split(";") if name.strip()]


def parseTrip(row: dict[str, str], where: str) -> Trip:
    """Build a Trip from one row of the trips file."""
    try:
        day = date.fromisoformat(row["date"])
    except ValueError:
        raise ValueError(f"{where}: bad date {row['date']!r}") from None
    try:
        km = Decimal(row["km"])
    except InvalidOperation:
        raise ValueError(f"{where}: bad distance {row['km']!r}") from None
    if not km.is_finite() or km <= 0:
        raise ValueError(f"{where}: distance must be above zero, got {row['km']!r}")
    if not row["car"] or not row["driver"]:
        raise ValueError(f"{where}: car and driver are required")
    riders = parseRiders(row["riders"])
    if row["driver"] in riders:
        raise ValueError(f"{where}: driver {row['driver']} is also listed as a rider")
    if len(set(riders)) != len(riders):
        raise ValueError(f"{where}: a rider is listed twice")
    return Trip(day, row["car"], km, row["driver"], tuple(riders))


def loadTrips(path: str) -> list[Trip]:
    """Read the trips file and return the trips in file order."""
    trips: list[Trip] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        for lineNo, row in enumerate(reader, start=2):
            values = {name: (row[name] or "").strip() for name in COLUMNS}
            trips.append(parseTrip(values, f"{path}:{lineNo}"))
    return trips
