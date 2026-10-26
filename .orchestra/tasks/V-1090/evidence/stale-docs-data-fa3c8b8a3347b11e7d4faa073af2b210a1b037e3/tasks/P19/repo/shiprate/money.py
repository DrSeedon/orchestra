"""Money amounts, held as integer cents."""


def parse_cents(text: str) -> int:
    """Parse an amount such as "4.90" or "12" into cents.

    Args:
        text: a non-negative amount with at most two digits after the point.

    Returns:
        The amount in cents.

    Raises:
        ValueError: if the text is not such an amount.
    """
    whole, _, fraction = text.strip().partition(".")
    if not whole.isdigit() or len(fraction) > 2 or (fraction and not fraction.isdigit()):
        raise ValueError(f"invalid amount {text!r}")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def format_cents(amount_cents: int) -> str:
    """Format cents as an amount with two digits after the point.

    Args:
        amount_cents: the amount in cents; it may be negative.

    Returns:
        The amount as text, for example "4.90".
    """
    sign = "-" if amount_cents < 0 else ""
    whole, rest = divmod(abs(amount_cents), 100)
    return f"{sign}{whole}.{rest:02d}"


def percent_of(amount_cents: int, percent: int) -> int:
    """A whole-number percentage of an amount, rounded half up to the cent.

    Args:
        amount_cents: the amount in cents, not negative.
        percent: the percentage, for example 8 for eight percent.

    Returns:
        The share in cents.
    """
    return (amount_cents * percent + 50) // 100
