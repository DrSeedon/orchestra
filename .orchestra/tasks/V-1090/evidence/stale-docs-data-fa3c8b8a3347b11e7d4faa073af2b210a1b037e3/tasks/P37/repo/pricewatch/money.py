"""Money amounts, kept as whole numbers of cents."""
import re

_AMOUNT = re.compile(r"^(-?)(\d+)(?:\.(\d{1,2}))?$")


def parseCents(text: str) -> int:
    """Return the amount in ``text`` ("12.30", "7", "0.5") as a number of cents."""
    match = _AMOUNT.match(text.strip())
    if match is None:
        raise ValueError("not an amount: {!r}".format(text))
    sign, whole, fraction = match.groups()
    cents = int(whole) * 100 + int((fraction or "0").ljust(2, "0"))
    return -cents if sign else cents


def formatCents(cents: int) -> str:
    """Return an amount with two digits after the point, for example "12.30" or "-0.55"."""
    whole, rest = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return "{}{}.{:02d}".format(sign, whole, rest)


def averageCents(amounts: list[int]) -> int:
    """Return the average of ``amounts``, rounded half up to a whole cent."""
    if not amounts:
        raise ValueError("cannot average an empty list of amounts")
    total = sum(amounts)
    count = len(amounts)
    return (2 * total + count) // (2 * count)
