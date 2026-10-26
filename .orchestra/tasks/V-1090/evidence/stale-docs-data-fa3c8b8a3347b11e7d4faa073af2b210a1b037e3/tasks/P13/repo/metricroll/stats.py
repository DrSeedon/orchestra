"""Summary statistics over a list of values."""

import math
from typing import List, NamedTuple


class Summary(NamedTuple):
    """Statistics of one window of values."""

    n: int
    min: float
    max: float
    mean: float
    p50: float
    p95: float


def percentile(values: List[float], q: float) -> float:
    """Percentile ``q`` (0-100) with linear interpolation between ranks."""
    if not values:
        raise ValueError("percentile of empty list")
    if not 0 <= q <= 100:
        raise ValueError(f"q must be between 0 and 100, got {q}")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(values: List[float]) -> Summary:
    """Count, min, max, mean, median and 95th percentile of ``values``."""
    if not values:
        raise ValueError("cannot summarize an empty window")
    return Summary(
        n=len(values),
        min=min(values),
        max=max(values),
        mean=sum(values) / len(values),
        p50=percentile(values, 50),
        p95=percentile(values, 95),
    )
