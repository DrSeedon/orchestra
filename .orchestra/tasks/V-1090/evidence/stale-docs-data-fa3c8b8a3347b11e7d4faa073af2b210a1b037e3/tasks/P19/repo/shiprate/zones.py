"""Shipping zones per destination country."""

from shiprate.csvfiles import read_rows


def load_zones(path: str) -> dict[str, str]:
    """Read the zone table.

    Args:
        path: CSV file with the columns country and zone.

    Returns:
        The zone of every country, keyed by country; both in upper case.

    Raises:
        ValueError: if a field is empty or a country appears twice.
    """
    zones: dict[str, str] = {}
    for line_no, row in read_rows(path, ("country", "zone")):
        country = row["country"].upper()
        if not country or not row["zone"]:
            raise ValueError(f"{path}:{line_no}: country and zone are required")
        if country in zones:
            raise ValueError(f"{path}:{line_no}: country {country} appears twice")
        zones[country] = row["zone"].upper()
    return zones


def zone_for(country: str, zones: dict[str, str]) -> str:
    """Look up the zone of a destination country.

    Args:
        country: the country code, in any case.
        zones: the zone table, as returned by load_zones.

    Returns:
        The zone of the country.

    Raises:
        ValueError: if the country is not in the zone table.
    """
    zone = zones.get(country.strip().upper())
    if zone is None:
        raise ValueError(f"no shipping zone for country {country!r}")
    return zone
