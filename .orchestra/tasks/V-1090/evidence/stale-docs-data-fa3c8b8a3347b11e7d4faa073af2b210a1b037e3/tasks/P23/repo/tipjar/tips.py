"""Tip percentages and totals."""
from decimal import Decimal

from .money import percent_of

MAX_TIP_PERCENT = 100


def parse_percent(text: str | None) -> int | None:
    """Parse a tip percentage such as "15" or "15%".

    Returns None when text is None or empty, which means that no tip was given.
    Raises ValueError for anything that is not a whole number from 0 to
    MAX_TIP_PERCENT.
    """
    if text is None or not text.strip():
        return None
    cleaned = text.strip().removesuffix("%").strip()
    if not cleaned.isdigit():
        raise ValueError("not a percentage: {!r}".format(text))
    percent = int(cleaned)
    if percent > MAX_TIP_PERCENT:
        raise ValueError("tip above {}%: {!r}".format(MAX_TIP_PERCENT, text))
    return percent


def tip_amount(subtotal: Decimal, percent: int | None) -> Decimal | None:
    """Return the tip for a subtotal, rounded half up, or None when no tip was given."""
    if percent is None:
        return None
    return percent_of(subtotal, percent)


def total_with_tip(subtotal: Decimal, tip: Decimal | None) -> Decimal:
    """Add the tip, if there is one, to the subtotal."""
    if tip is None:
        return subtotal
    return subtotal + tip
