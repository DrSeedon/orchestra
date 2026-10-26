"""Money amounts.

Amounts are held as whole cents in an ``int``: ``12.30`` is ``1230``. Text
amounts in files and on the command line have at most two decimals.
"""
import re

AMOUNT_PATTERN = re.compile(r"^(\d+)(?:\.(\d{1,2}))?$")


def parse_cents(text: str) -> int:
    """Parse an amount such as ``"12.30"``, ``"12.3"`` or ``"12"`` into cents."""
    match = AMOUNT_PATTERN.match(text.strip())
    if not match:
        raise ValueError(f"not an amount: {text!r}")
    whole, fraction = match.groups()
    return int(whole) * 100 + int((fraction or "0").ljust(2, "0"))


def format_cents(cents: int) -> str:
    """Format cents as an amount with two decimals: ``1230`` gives ``"12.30"``."""
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"

