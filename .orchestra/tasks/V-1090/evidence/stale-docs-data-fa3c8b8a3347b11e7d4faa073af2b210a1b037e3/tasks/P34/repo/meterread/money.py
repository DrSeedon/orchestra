"""Money amounts: two-place Decimal values read from and written to text."""
import re
from decimal import ROUND_HALF_UP, Decimal

AMOUNT_PATTERN = re.compile(r"^\d+(?:\.\d{1,2})?$")
STEP = Decimal("0.01")


def parse_amount(text: str) -> tuple[Decimal | None, str | None]:
    """Read a money amount such as ``12.30`` or ``7``.

    :param text: the amount as written in a file
    :returns: the amount and None, or None and an error message
    """
    cleaned = text.strip()
    if not AMOUNT_PATTERN.match(cleaned):
        return None, f"not an amount: {text!r}"
    return Decimal(cleaned).quantize(STEP), None


def round_amount(value: Decimal) -> Decimal:
    """Round a value to two places, with halves rounded up.

    :param value: the exact value
    :returns: the rounded amount
    """
    return value.quantize(STEP, rounding=ROUND_HALF_UP)


def format_amount(amount: Decimal) -> str:
    """Write an amount with two digits after the point, for example ``12.30``.

    :param amount: the amount
    :returns: the text of the amount
    """
    return str(round_amount(amount))
