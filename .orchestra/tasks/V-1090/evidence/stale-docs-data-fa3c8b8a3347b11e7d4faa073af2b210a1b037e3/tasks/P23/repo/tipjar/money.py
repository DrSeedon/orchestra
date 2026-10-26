"""Parse, round and format money amounts."""
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")


def parse_amount(text: str) -> Decimal:
    """Parse an amount such as "12.5" or "12.50".

    Raises ValueError for text that is not a number, for negative amounts and for
    amounts with more than two digits after the point.
    """
    cleaned = text.strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("not an amount: {!r}".format(text)) from None
    if not value.is_finite() or value < 0:
        raise ValueError("not an amount: {!r}".format(text))
    if value != value.quantize(TWO_PLACES, rounding=ROUND_DOWN):
        raise ValueError("more than two digits after the point: {!r}".format(text))
    return value.quantize(TWO_PLACES)


def round_amount(value: Decimal) -> Decimal:
    """Round to two places, halves upwards: 8.175 becomes 8.18."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_down(value: Decimal) -> Decimal:
    """Round down to two places: 17.909 becomes 17.90."""
    return value.quantize(TWO_PLACES, rounding=ROUND_DOWN)


def percent_of(amount: Decimal, percent: int) -> Decimal:
    """Return the given percentage of an amount, rounded with round_amount."""
    return round_amount(amount * percent / 100)


def format_amount(value: Decimal) -> str:
    """Format an amount with two digits after the point, such as "12.30"."""
    return "{:.2f}".format(value)
