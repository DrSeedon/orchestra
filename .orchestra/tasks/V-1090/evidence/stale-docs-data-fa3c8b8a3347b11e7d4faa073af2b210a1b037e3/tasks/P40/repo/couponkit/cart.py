"""The cart file: one CSV row per product in the cart."""
import csv
from dataclasses import dataclass
from decimal import Decimal

from couponkit.errors import AmountError, CartError
from couponkit.money import ZERO, parse_amount

COLUMNS = ("sku", "quantity", "price")


@dataclass(frozen=True)
class CartLine:
    """One product in the cart: how many, and the price of one."""

    sku: str
    quantity: int
    price: Decimal

    @property
    def total(self) -> Decimal:
        """The price of all items of this line."""
        return self.price * self.quantity


def parse_line(row: dict[str, str], line: int) -> CartLine:
    """Build a cart line from one CSV row; ``line`` is used in error messages."""
    sku = (row["sku"] or "").strip()
    if not sku:
        raise CartError(f"line {line}: sku is empty")
    quantity = (row["quantity"] or "").strip()
    if not quantity.isdecimal() or int(quantity) < 1:
        raise CartError(f"line {line}: quantity must be a whole number above zero")
    try:
        price = parse_amount(row["price"] or "")
    except AmountError as error:
        raise CartError(f"line {line}: {error}") from None
    return CartLine(sku=sku, quantity=int(quantity), price=price)


def load_cart(path: str) -> list[CartLine]:
    """Read the cart file at ``path``."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise CartError(f"{path}: missing column {missing[0]}")
        return [parse_line(row, line) for line, row in enumerate(reader, start=2)]


def cart_subtotal(lines: list[CartLine]) -> Decimal:
    """Return the sum of all line totals."""
    return sum((line.total for line in lines), ZERO)
