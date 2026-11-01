"""Parse, round and format money amounts."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def parseAmount(text: str) -> Decimal:
    """Parse a money amount such as ``"1250.50"`` or ``"1,250.50"``."""
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        raise ValueError("empty amount")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a money amount: {text!r}") from None
    if value != value.quantize(CENT):
        raise ValueError(f"more than two decimal places: {text!r}")
    return value


def roundMoney(value: Decimal) -> Decimal:
    """Round to whole cents, halves away from zero."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def formatMoney(value: Decimal) -> str:
    """Format an amount with a thousands separator and two decimals."""
    return f"{roundMoney(value):,.2f}"


def sumMoney(values: list[Decimal]) -> Decimal:
    """Add amounts and round the total."""
    return roundMoney(sum(values, ZERO))
