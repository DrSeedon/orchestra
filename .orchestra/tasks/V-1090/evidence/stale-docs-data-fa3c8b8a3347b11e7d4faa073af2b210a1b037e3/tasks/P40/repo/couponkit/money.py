"""Money amounts: parsing, rounding and formatting."""
import re
from decimal import ROUND_HALF_UP, Decimal

from couponkit.errors import AmountError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

_AMOUNT = re.compile(r"\d+(\.\d{1,2})?")


def parse_amount(text: str) -> Decimal:
    """Return the amount written as ``text``, for example ``"12.30"``.

    An amount is zero or more and has at most two digits after the point.
    """
    text = text.strip()
    if not _AMOUNT.fullmatch(text):
        raise AmountError(f"not an amount: {text!r}")
    return Decimal(text).quantize(CENT)


def round_amount(amount: Decimal) -> Decimal:
    """Round ``amount`` to two digits after the point, halves away from zero."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def format_amount(amount: Decimal) -> str:
    """Return ``amount`` as text with two digits after the point."""
    return f"{round_amount(amount):.2f}"
