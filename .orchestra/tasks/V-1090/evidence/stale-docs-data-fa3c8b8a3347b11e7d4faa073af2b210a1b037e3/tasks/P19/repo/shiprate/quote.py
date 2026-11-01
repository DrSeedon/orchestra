"""Quote the shipping price of every parcel of a parcel list.

Usage: python -m shiprate.quote DATA_DIR PARCELS OUTPUT [--settings FILE]

DATA_DIR holds the zone table zones.csv and the rate table rates.csv.
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass

from shiprate.money import format_cents, percent_of
from shiprate.parcels import Parcel, load_parcels
from shiprate.rates import Band, load_rates, price_for
from shiprate.settings import Settings, load_settings
from shiprate.zones import load_zones, zone_for

QUOTE_COLUMNS = ("id", "zone", "base", "fuel", "total", "currency")


@dataclass(frozen=True)
class Quote:
    """The price of one parcel.

    Attributes:
        parcel_id: the id of the parcel.
        zone: the zone of its destination.
        base_cents: the price of its rate band.
        fuel_cents: the fuel surcharge.
    """

    parcel_id: str
    zone: str
    base_cents: int
    fuel_cents: int

    @property
    def total_cents(self) -> int:
        """The base rate plus the fuel surcharge."""
        return self.base_cents + self.fuel_cents


def load_data(data_dir: str) -> tuple[dict[str, str], dict[str, list[Band]]]:
    """Read the zone table and the rate table of a data folder.

    Args:
        data_dir: folder with zones.csv and rates.csv.

    Returns:
        The zones per country and the rate bands per zone.
    """
    zones = load_zones(os.path.join(data_dir, "zones.csv"))
    rates = load_rates(os.path.join(data_dir, "rates.csv"))
    return zones, rates


def quote_parcel(parcel: Parcel, zones: dict[str, str], rates: dict[str, list[Band]],
                 settings: Settings) -> Quote:
    """Price one parcel, with the fuel surcharge and the weight limit of the settings.

    Returns:
        The quote of the parcel.

    Raises:
        ValueError: if the parcel is too heavy, or its country or weight has no rate.
    """
    if parcel.grams > settings.max_weight_grams:
        raise ValueError(f"parcel {parcel.parcel_id} weighs {parcel.grams} g, "
                         f"more than {settings.max_weight_grams} g")
    zone = zone_for(parcel.country, zones)
    base_cents = price_for(zone, parcel.grams, rates)
    return Quote(parcel.parcel_id, zone, base_cents, percent_of(base_cents, settings.fuel_percent))


def write_quotes(path: str, quotes: list[Quote], settings: Settings) -> None:
    """Write the quotes as CSV, one row per parcel, with the currency of the settings."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(QUOTE_COLUMNS)
        for quote in quotes:
            writer.writerow([quote.parcel_id, quote.zone, format_cents(quote.base_cents),
                             format_cents(quote.fuel_cents), format_cents(quote.total_cents),
                             settings.currency])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shiprate.quote",
                                     description="Quote the shipping price of a parcel list.")
    parser.add_argument("data_dir", help="folder with zones.csv and rates.csv")
    parser.add_argument("parcels", help="CSV parcel list (id,country,grams)")
    parser.add_argument("output", help="CSV file to write")
    parser.add_argument("--settings", help="JSON settings file")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.settings)
        zones, rates = load_data(args.data_dir)
        quotes = [quote_parcel(parcel, zones, rates, settings) for parcel in load_parcels(args.parcels)]
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    write_quotes(args.output, quotes, settings)
    total_cents = sum(quote.total_cents for quote in quotes)
    print(f"quoted {len(quotes)} parcels, total {format_cents(total_cents)} {settings.currency}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
