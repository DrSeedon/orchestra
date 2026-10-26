"""The size chart: for each size, the range of each body measurement it is made for."""
import csv
from dataclasses import dataclass
from enum import Enum


class Measure(Enum):
    """A body measurement that the size chart gives a range for."""

    CHEST = "chest"
    WAIST = "waist"
    HIP = "hip"


@dataclass(frozen=True)
class SizeRange:
    """The smallest and the largest measurement, in cm, that a size is made for."""

    low: float
    high: float

    def contains(self, value: float) -> bool:
        """Tell if ``value`` is inside the range.

        Args:
            value: A measurement in cm.

        Returns:
            True if ``value`` is between ``low`` and ``high``, both included.
        """
        return self.low <= value <= self.high


@dataclass(frozen=True)
class Size:
    """One row of the size chart."""

    label: str
    ranges: dict[Measure, SizeRange]


def chart_columns() -> list[str]:
    """Return the columns that a size chart file must have.

    Returns:
        ``size``, then a ``_min`` and a ``_max`` column for each measure.
    """
    columns = ["size"]
    for measure in Measure:
        columns += [f"{measure.value}_min", f"{measure.value}_max"]
    return columns


def parse_size(row: dict[str, str], line: int) -> Size:
    """Build one size from a row of the size chart file.

    Args:
        row: The row, from ``csv.DictReader``.
        line: The line number of the row, for error messages.

    Returns:
        The size of the row.

    Raises:
        ValueError: If the label is empty, a value is not a number, or a
            minimum is above its maximum.
    """
    label = (row["size"] or "").strip()
    if not label:
        raise ValueError(f"line {line}: size label is empty")
    ranges = {}
    for measure in Measure:
        try:
            low = float(row[f"{measure.value}_min"])
            high = float(row[f"{measure.value}_max"])
        except (TypeError, ValueError):
            raise ValueError(f"line {line}: bad {measure.value} value") from None
        if low > high:
            raise ValueError(f"line {line}: {measure.value} minimum is above the maximum")
        ranges[measure] = SizeRange(low, high)
    return Size(label=label, ranges=ranges)


def load_chart(path: str) -> list[Size]:
    """Read a size chart file, a CSV file with the columns of ``chart_columns()``.

    Args:
        path: The file to read.

    Returns:
        The sizes, in file order.

    Raises:
        ValueError: If a column is missing, a row is bad, or a label appears twice.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in chart_columns() if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column {missing[0]}")
        sizes = [parse_size(row, line) for line, row in enumerate(reader, start=2)]
    labels = [size.label.upper() for size in sizes]
    for label in labels:
        if labels.count(label) > 1:
            raise ValueError(f"{path}: size {label} appears twice")
    return sizes


def find_size(chart: list[Size], label: str) -> Size:
    """Return the size called ``label``; upper and lower case are the same.

    Args:
        chart: The sizes of the chart.
        label: The label to look for.

    Returns:
        The size with that label.

    Raises:
        KeyError: If the chart has no size with that label.
    """
    for size in chart:
        if size.label.upper() == label.strip().upper():
            return size
    raise KeyError(f"unknown size: {label}")
