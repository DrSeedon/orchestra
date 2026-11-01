"""The parcel list."""

from dataclasses import dataclass

from shiprate.csvfiles import read_rows


@dataclass(frozen=True)
class Parcel:
    """A parcel of the parcel list.

    Attributes:
        parcel_id: the id of the parcel.
        country: the destination country code, upper case.
        grams: the weight in grams.
    """

    parcel_id: str
    country: str
    grams: int


def load_parcels(path: str) -> list[Parcel]:
    """Read the parcel list.

    Args:
        path: CSV file with the columns id, country and grams.

    Returns:
        The parcels in file order.

    Raises:
        ValueError: if an id is empty or repeated, or a weight is not valid.
    """
    parcels: list[Parcel] = []
    seen: set[str] = set()
    for line_no, row in read_rows(path, ("id", "country", "grams")):
        if not row["id"] or row["id"] in seen:
            raise ValueError(f"{path}:{line_no}: empty or repeated parcel id {row['id']!r}")
        if not row["grams"].isdigit() or int(row["grams"]) == 0:
            raise ValueError(f"{path}:{line_no}: invalid weight {row['grams']!r}")
        seen.add(row["id"])
        parcels.append(Parcel(row["id"], row["country"].upper(), int(row["grams"])))
    return parcels
