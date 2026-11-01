"""The shopping cart and its lines."""
from dataclasses import dataclass

from cartkit.catalog import Catalog, Product
from cartkit.errors import InvalidQuantityError, UnknownProductError

MAX_QUANTITY = 99


@dataclass
class CartLine:
    """A product and how many of it are in the cart."""

    product: Product
    quantity: int

    @property
    def line_total_cents(self) -> int:
        """Return unit price times quantity."""
        return self.product.unit_price_cents * self.quantity


class Cart:
    """A cart of products from one catalog."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._lines: dict[str, CartLine] = {}

    def add(self, sku: str, quantity: int = 1) -> None:
        """Add a quantity of a product, merging with an existing line."""
        product = self._catalog.get(sku)
        current = self._lines[sku].quantity if sku in self._lines else 0
        self._check_quantity(current + quantity)
        self._lines[sku] = CartLine(product, current + quantity)

    def set_quantity(self, sku: str, quantity: int) -> None:
        """Replace the quantity of a line that is already in the cart."""
        if sku not in self._lines:
            raise UnknownProductError("SKU not in cart: {}".format(sku))
        self._check_quantity(quantity)
        self._lines[sku].quantity = quantity

    def remove(self, sku: str) -> None:
        """Remove a line from the cart."""
        if sku not in self._lines:
            raise UnknownProductError("SKU not in cart: {}".format(sku))
        del self._lines[sku]

    def lines(self) -> list[CartLine]:
        """Return the cart lines ordered by SKU."""
        return [self._lines[sku] for sku in sorted(self._lines)]

    def subtotal(self) -> int:
        """Return the sum of all line totals, in cents."""
        return sum(line.line_total_cents for line in self._lines.values())

    def total_weight_grams(self) -> int:
        """Return the shipping weight of the whole cart."""
        return sum(line.product.weight_grams * line.quantity for line in self._lines.values())

    def is_empty(self) -> bool:
        """Return True when the cart has no lines."""
        return not self._lines

    @staticmethod
    def _check_quantity(quantity: int) -> None:
        if quantity < 1 or quantity > MAX_QUANTITY:
            raise InvalidQuantityError(
                "quantity must be between 1 and {}, got {}".format(MAX_QUANTITY, quantity)
            )
