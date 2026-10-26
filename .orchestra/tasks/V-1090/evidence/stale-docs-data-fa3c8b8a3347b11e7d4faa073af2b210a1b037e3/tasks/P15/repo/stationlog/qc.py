"""Quality control: blank out measurements outside plausible ranges."""

import logging
from dataclasses import replace

from .readings import Reading

logger = logging.getLogger(__name__)

LIMITS: dict[str, tuple[float, float]] = {
    "temp_c": (-60.0, 60.0),
    "humidity": (0.0, 100.0),
    "pressure_hpa": (850.0, 1090.0),
}


def out_of_range(name: str, value: float | None) -> bool:
    """True if ``value`` is present and outside the limits for ``name``."""
    if value is None:
        return False
    low, high = LIMITS[name]
    return not low <= value <= high


def check_reading(reading: Reading) -> Reading:
    """Return a copy of ``reading`` with implausible measurements set to None."""
    changes: dict[str, float | None] = {}
    for name in LIMITS:
        value = getattr(reading, name)
        if out_of_range(name, value):
            logger.warning(
                "%s %s: %s=%s out of range, dropped",
                reading.station, reading.time.isoformat(), name, value,
            )
            changes[name] = None
    return replace(reading, **changes) if changes else reading


def apply_qc(readings: list[Reading]) -> list[Reading]:
    """Run :func:`check_reading` on every reading."""
    return [check_reading(r) for r in readings]
