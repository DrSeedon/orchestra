"""Money helpers: parse, format and add amounts."""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")


def parseAmount(text: str) -> Decimal:
    """Parse an amount such as "12.5", "1,250.00" or "-3.10" with two places."""
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        raise ValueError("empty amount")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"not an amount: {text!r}")
    return value.quantize(TWO_PLACES)


def formatAmount(value: Decimal) -> str:
    """Format an amount with two digits after the point, for example "1250.00"."""
    value = value.quantize(TWO_PLACES)
    if value.is_zero():
        value = abs(value)
    return str(value)


def sumAmounts(values: Iterable[Decimal]) -> Decimal:
    """Add amounts; the sum of no amounts is 0.00."""
    total = Decimal("0.00")
    for value in values:
        total += value
    return total.quantize(TWO_PLACES)
