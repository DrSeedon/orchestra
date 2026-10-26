"""Money helpers. Amounts are integer cents everywhere in cartkit."""
import re

from cartkit.errors import InvalidPriceError

_PRICE_RE = re.compile(r"^\$?(\d+)(?:\.(\d{1,2}))?$")


def parse_price(text: str) -> int:
    """Parse a price such as "12.5" or "$3.99" into cents."""
    match = _PRICE_RE.match(text.strip())
    if match is None:
        raise InvalidPriceError("invalid price: {!r}".format(text))
    dollars, fraction = match.groups()
    fraction = (fraction or "").ljust(2, "0")
    return int(dollars) * 100 + int(fraction)


def format_price(amount_cents: int) -> str:
    """Format cents for display, e.g. 1299 -> "$12.99"."""
    sign = "-" if amount_cents < 0 else ""
    dollars, rest = divmod(abs(amount_cents), 100)
    return "{}${}.{:02d}".format(sign, dollars, rest)


def percent_of(amount_cents: int, basis_points: int) -> int:
    """Return basis_points / 10000 of an amount, rounded half up to whole cents."""
    return (amount_cents * basis_points + 5000) // 10000
