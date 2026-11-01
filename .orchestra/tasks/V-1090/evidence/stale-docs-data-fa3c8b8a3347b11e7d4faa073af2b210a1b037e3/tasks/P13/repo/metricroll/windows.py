"""Cut series into fixed-width time windows and summarize each window."""

from typing import Dict, List, Tuple

from metricroll.series import Sample, values_of
from metricroll.stats import Summary, summarize

DEFAULT_WIDTH = 300


def window_start(timestamp: int, width: int) -> int:
    """Start of the window of ``width`` seconds that contains ``timestamp``."""
    if width <= 0:
        raise ValueError(f"window width must be positive, got {width}")
    return timestamp - timestamp % width


def bucket(samples: List[Sample], width: int) -> Dict[int, List[Sample]]:
    """Group samples by window start."""
    buckets: Dict[int, List[Sample]] = {}
    for sample in samples:
        buckets.setdefault(window_start(sample.timestamp, width), []).append(sample)
    return buckets


def rollup(samples: List[Sample], width: int) -> List[Tuple[int, Summary]]:
    """Summaries per window, ordered by window start. Empty windows are left out."""
    buckets = bucket(samples, width)
    return [(start, summarize(values_of(buckets[start]))) for start in sorted(buckets)]


def rollup_all(
    series: Dict[str, List[Sample]], width: int
) -> Dict[str, List[Tuple[int, Summary]]]:
    """Roll up every metric of ``series``."""
    return {name: rollup(samples, width) for name, samples in sorted(series.items())}
