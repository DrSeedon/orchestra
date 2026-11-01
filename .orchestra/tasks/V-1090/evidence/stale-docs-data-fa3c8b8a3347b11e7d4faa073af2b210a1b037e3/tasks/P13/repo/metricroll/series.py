"""Parse metric samples and group them into per-metric series."""

from typing import Dict, Iterable, List, NamedTuple, Tuple


class Sample(NamedTuple):
    """One measurement: unix timestamp in seconds and a value."""

    timestamp: int
    value: float


def parse_line(line: str) -> Tuple[str, Sample]:
    """Parse ``"<metric> <timestamp> <value>"``, e.g. ``"cpu 1700000000 42.5"``."""
    parts = line.split()
    if len(parts) != 3:
        raise ValueError(f"expected 3 fields, got {len(parts)}: {line!r}")
    name, ts_text, value_text = parts
    try:
        timestamp = int(ts_text)
        value = float(value_text)
    except ValueError:
        raise ValueError(f"bad timestamp or value: {line!r}") from None
    if timestamp < 0:
        raise ValueError(f"negative timestamp: {line!r}")
    return name, Sample(timestamp, value)


def load_series(lines: Iterable[str]) -> Dict[str, List[Sample]]:
    """Group sample lines by metric name; each series is sorted by time.

    Blank lines and lines starting with ``#`` are ignored.
    """
    series: Dict[str, List[Sample]] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sample = parse_line(stripped)
        series.setdefault(name, []).append(sample)
    for samples in series.values():
        samples.sort()
    return series


def read_series(path: str) -> Dict[str, List[Sample]]:
    """Load the samples file at ``path`` with :func:`load_series`."""
    with open(path, encoding="utf-8") as handle:
        return load_series(handle)


def values_of(samples: List[Sample]) -> List[float]:
    """Return just the values of ``samples``."""
    return [s.value for s in samples]
