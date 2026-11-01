"""The people file: the body measurements of each person."""
import csv
from dataclasses import dataclass

from sizechart.chart import Measure
from sizechart.units import parse_unit, to_cm


@dataclass(frozen=True)
class Person:
    """One person and their measurements, in cm."""

    name: str
    measurements: dict[Measure, float]


def people_columns() -> list[str]:
    """Return the columns that a people file must have.

    Returns:
        ``name``, one column per measure, then ``unit``.
    """
    return ["name"] + [measure.value for measure in Measure] + ["unit"]


def parse_person(row: dict[str, str], line: int) -> Person:
    """Build one person from a row of the people file.

    Args:
        row: The row, from ``csv.DictReader``.
        line: The line number of the row, for error messages.

    Returns:
        The person, with every measurement converted to cm.

    Raises:
        ValueError: If the name is empty, the unit is unknown, or a
            measurement is not a number above zero.
    """
    name = (row["name"] or "").strip()
    if not name:
        raise ValueError(f"line {line}: name is empty")
    try:
        unit = parse_unit(row["unit"] or "")
    except ValueError as error:
        raise ValueError(f"line {line}: {error}") from None
    measurements = {}
    for measure in Measure:
        try:
            value = float(row[measure.value])
        except (TypeError, ValueError):
            raise ValueError(f"line {line}: bad {measure.value} value") from None
        if value <= 0:
            raise ValueError(f"line {line}: {measure.value} must be above zero")
        measurements[measure] = to_cm(value, unit)
    return Person(name=name, measurements=measurements)


def load_people(path: str) -> list[Person]:
    """Read a people file, a CSV file with the columns of ``people_columns()``.

    Args:
        path: The file to read.

    Returns:
        The people, in file order.

    Raises:
        ValueError: If a column is missing or a row is bad.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in people_columns() if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column {missing[0]}")
        return [parse_person(row, line) for line, row in enumerate(reader, start=2)]
