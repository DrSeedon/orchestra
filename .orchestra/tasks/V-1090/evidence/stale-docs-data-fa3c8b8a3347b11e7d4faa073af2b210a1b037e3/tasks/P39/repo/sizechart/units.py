"""Units of length, and conversion of lengths to centimetres."""
from enum import Enum


class Unit(Enum):
    """A unit that a body measurement can be given in."""

    CM = "cm"
    INCH = "in"


CM_PER_INCH = 2.54


def parse_unit(text: str) -> Unit:
    """Return the unit that ``text`` names.

    Args:
        text: The unit as written in a file, ``cm`` or ``in``.

    Returns:
        The matching unit.

    Raises:
        ValueError: If ``text`` names no known unit.
    """
    try:
        return Unit(text.strip().lower())
    except ValueError:
        raise ValueError(f"unknown unit: {text!r}") from None


def to_cm(value: float, unit: Unit) -> float:
    """Convert a length to centimetres.

    Args:
        value: The length, in ``unit``.
        unit: The unit of ``value``.

    Returns:
        The length in centimetres.
    """
    if unit is Unit.INCH:
        return value * CM_PER_INCH
    return value
