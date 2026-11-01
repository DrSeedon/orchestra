"""Product catalog: SKUs, names, unit prices and shipping weights."""
import csv
import io
from dataclasses import dataclass

from cartkit.errors import InvalidPriceError, UnknownProductError
from cartkit.money import parse_price


@dataclass(frozen=True)
class Product:
    """One product that can be put in a cart."""

    sku: str
    name: str
    unit_price_cents: int
    weight_grams: int


class Catalog:
    """Products indexed by SKU."""

    def __init__(self, products: list[Product]) -> None:
        self._products = {product.sku: product for product in products}

    def get(self, sku: str) -> Product:
        """Return the product for a SKU."""
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownProductError("unknown SKU: {}".format(sku)) from None

    def skus(self) -> list[str]:
        """Return all SKUs in sorted order."""
        return sorted(self._products)

    def __len__(self) -> int:
        return len(self._products)


def load_catalog(csv_text: str) -> Catalog:
    """Build a catalog from CSV text with columns sku,name,price,weight_grams."""
    products = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row_number, row in enumerate(reader, start=2):
        try:
            unit_price_cents = parse_price(row["price"])
        except InvalidPriceError as exc:
            raise InvalidPriceError("row {}: {}".format(row_number, exc)) from None
        products.append(
            Product(
                sku=row["sku"].strip(),
                name=row["name"].strip(),
                unit_price_cents=unit_price_cents,
                weight_grams=int(row["weight_grams"]),
            )
        )
    return Catalog(products)
