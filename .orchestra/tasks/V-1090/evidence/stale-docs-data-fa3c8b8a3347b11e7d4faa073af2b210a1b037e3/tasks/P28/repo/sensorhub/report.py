"""Build and write the JSON summary of all sensors."""
import json

from sensorhub.settings import Settings
from sensorhub.stats import SensorStats


def stats_entry(item: SensorStats, settings: Settings) -> dict[str, object]:
    """Return the JSON object of one sensor, with values rounded to settings.decimals."""
    return {
        "sensor": item.sensor,
        "count": item.count,
        "min": round(item.low, settings.decimals),
        "max": round(item.high, settings.decimals),
        "mean": round(item.mean, settings.decimals),
        "gaps": item.gaps,
        "last": item.last.isoformat(),
    }


def build_summary(stats: list[SensorStats], settings: Settings) -> dict[str, object]:
    """Return the whole summary: the sensors and the settings it was made with."""
    return {
        "max_gap": settings.max_gap,
        "min_readings": settings.min_readings,
        "sensors": [stats_entry(item, settings) for item in stats],
    }


def write_summary(summary: dict[str, object], path: str) -> str | None:
    """Write the summary as JSON. Return an error message, or None on success."""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        return f"cannot write {path}: {exc.strerror}"
    return None
