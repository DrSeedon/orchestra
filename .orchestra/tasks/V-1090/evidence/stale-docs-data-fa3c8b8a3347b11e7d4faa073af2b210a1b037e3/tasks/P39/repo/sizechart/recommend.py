"""Size advice: the smallest size of the chart that fits a person."""
from typing import Optional

from sizechart.chart import Size
from sizechart.people import Person


def fits(size: Size, person: Person) -> bool:
    """Tell if every measurement of ``person`` is inside the ranges of ``size``.

    Args:
        size: A size of the chart.
        person: The person to check.

    Returns:
        True if the size fits on every measure.
    """
    return all(size.ranges[measure].contains(value)
               for measure, value in person.measurements.items())


def recommend(chart: list[Size], person: Person) -> Optional[Size]:
    """Return the first size of the chart that fits ``person``.

    Args:
        chart: The sizes, from small to large.
        person: The person to find a size for.

    Returns:
        The first fitting size, or None if no size fits.
    """
    for size in chart:
        if fits(size, person):
            return size
    return None
