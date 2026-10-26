"""Per-sensor statistics: count, lowest, highest and mean value, gaps in the data."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sensorhub.readings import Reading
from sensorhub.settings import Settings


@dataclass(frozen=True)
class SensorStats:
    """Statistics of one sensor."""

    sensor: str
    count: int
    low: float
    high: float
    mean: float
    gaps: int
    last: datetime


def group_by_sensor(readings: list[Reading]) -> dict[str, list[Reading]]:
    """Group readings by sensor, keeping their order inside each group."""
    groups: dict[str, list[Reading]] = {}
    for reading in readings:
        groups.setdefault(reading.sensor, []).append(reading)
    return groups


def count_gaps(readings: list[Reading], max_gap: timedelta) -> int:
    """Count the places where two readings in a row are more than max_gap apart."""
    return sum(1 for first, second in zip(readings, readings[1:]) if second.time - first.time > max_gap)


def sensor_stats(readings: list[Reading], settings: Settings) -> list[SensorStats]:
    """Return statistics per sensor, sorted by sensor name.

    Sensors with fewer than settings.min_readings readings are left out and reported.
    """
    max_gap = timedelta(minutes=settings.max_gap)
    result: list[SensorStats] = []
    for sensor, group in sorted(group_by_sensor(readings).items()):
        if len(group) < settings.min_readings:
            print(f"{sensor}: only {len(group)} readings, left out of the summary")
            continue
        values = [reading.value for reading in group]
        result.append(SensorStats(
            sensor=sensor,
            count=len(group),
            low=min(values),
            high=max(values),
            mean=sum(values) / len(values),
            gaps=count_gaps(group, max_gap),
            last=group[-1].time,
        ))
    return result
