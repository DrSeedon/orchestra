"""Parse and format money amounts.

Amounts are held as integer cents, so sums and differences are exact.
"""
import re

AMOUNT = re.compile(r"^(-?)(\d+)(?:\.(\d{1,2}))?$")


def to_cents(text: str) -> int:
    """Turn an amount such as "1250", "1250.5" or "-12.30" into integer cents."""
    match = AMOUNT.match(text.strip())
    if match is None:
        raise ValueError(f"bad amount {text!r}")
    sign, whole, fraction = match.groups()
    amount_cents = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
    return -amount_cents if sign else amount_cents


def format_cents(amount_cents: int) -> str:
    """Format integer cents with two digits after the point, for example "1250.00"."""
    sign = "-" if amount_cents < 0 else ""
    whole, rest = divmod(abs(amount_cents), 100)
    return f"{sign}{whole}.{rest:02d}"
