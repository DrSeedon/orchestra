"""Price lists: CSV files with the columns sku, name and price."""
import csv
from dataclasses import dataclass

from pricewatch.money import formatCents, parseCents

COLUMNS = ("sku", "name", "price")


@dataclass
class PriceItem:
    """One product of a price list. ``price`` is in cents."""

    sku: str
    name: str
    price: int


def parseRow(row: dict, lineNumber: int) -> PriceItem:
    """Build a price item from one CSV row; ``lineNumber`` is used in messages."""
    sku = (row.get("sku") or "").strip()
    name = (row.get("name") or "").strip()
    if not sku or not name:
        raise ValueError("line {}: sku and name must not be empty".format(lineNumber))
    try:
        price = parseCents(row.get("price") or "")
    except ValueError:
        raise ValueError("line {}: bad price {!r}".format(lineNumber, row.get("price"))) from None
    if price <= 0:
        raise ValueError("line {}: price must be above zero".format(lineNumber))
    return PriceItem(sku=sku, name=name, price=price)


def loadPriceList(path: str) -> dict[str, PriceItem]:
    """Read the price list at ``path`` and return its items by sku, in file order."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("missing column {}".format(", ".join(missing)))
        items = {}
        for lineNumber, row in enumerate(reader, start=2):
            item = parseRow(row, lineNumber)
            if item.sku in items:
                raise ValueError("line {}: sku {} appears twice".format(lineNumber, item.sku))
            items[item.sku] = item
    return items


def savePriceList(path: str, items: dict[str, PriceItem]) -> None:
    """Write ``items`` to ``path`` as a price list."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for item in items.values():
            writer.writerow([item.sku, item.name, formatCents(item.price)])
