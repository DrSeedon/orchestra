"""Rate bands per zone and weight."""

from dataclasses import dataclass

from shiprate.csvfiles import read_rows
from shiprate.money import parse_cents


@dataclass(frozen=True)
class Band:
    """One rate band of a zone.

    Attributes:
        zone: the zone of the band.
        max_grams: the heaviest weight of the band, inclusive.
        price_cents: the price of a parcel in the band.
    """

    zone: str
    max_grams: int
    price_cents: int


def load_rates(path: str) -> dict[str, list[Band]]:
    """Read the rate table.

    Args:
        path: CSV file with the columns zone, max_grams and price.

    Returns:
        The bands of every zone, lightest band first.

    Raises:
        ValueError: if a weight or a price cannot be read.
    """
    rates: dict[str, list[Band]] = {}
    for line_no, row in read_rows(path, ("zone", "max_grams", "price")):
        if not row["max_grams"].isdigit():
            raise ValueError(f"{path}:{line_no}: invalid weight {row['max_grams']!r}")
        try:
            price_cents = parse_cents(row["price"])
        except ValueError as err:
            raise ValueError(f"{path}:{line_no}: {err}") from err
        zone = row["zone"].upper()
        rates.setdefault(zone, []).append(Band(zone, int(row["max_grams"]), price_cents))
    for bands in rates.values():
        bands.sort(key=lambda band: band.max_grams)
    return rates


def price_for(zone: str, grams: int, rates: dict[str, list[Band]]) -> int:
    """The base rate of a parcel, in cents.

    Args:
        zone: the zone of the destination.
        grams: the weight of the parcel.
        rates: the bands per zone, as returned by load_rates.

    Returns:
        The price of the lightest band of the zone that takes the weight.

    Raises:
        ValueError: if no band of the zone takes the weight.
    """
    for band in rates.get(zone, []):
        if grams <= band.max_grams:
            return band.price_cents
    raise ValueError(f"no rate for {grams} g in zone {zone}")
