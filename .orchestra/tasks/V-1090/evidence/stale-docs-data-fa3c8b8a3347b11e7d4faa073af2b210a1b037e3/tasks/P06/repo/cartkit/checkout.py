"""Tax, shipping and the final receipt for a cart."""
from dataclasses import dataclass

from cartkit.cart import Cart
from cartkit.errors import EmptyCartError, UnknownRegionError
from cartkit.money import format_price, percent_of

# Sales tax per region, in basis points (725 = 7.25%).
TAX_RATES_BP = {"CA": 725, "NY": 400, "OR": 0, "TX": 625}

# Shipping: a base fee per region plus a fee per started kilogram.
SHIPPING_BASE_CENTS = {"CA": 499, "NY": 599, "OR": 499, "TX": 549}
SHIPPING_PER_KG_CENTS = 150
FREE_SHIPPING_FROM_CENTS = 7500


@dataclass(frozen=True)
class Receipt:
    """The money totals of one checkout."""

    subtotal_cents: int
    tax_cents: int
    shipping_cents: int

    @property
    def total_cents(self) -> int:
        """Return subtotal plus tax plus shipping."""
        return self.subtotal_cents + self.tax_cents + self.shipping_cents


def compute_tax(subtotal_cents: int, region: str) -> int:
    """Return the sales tax for a subtotal in a region."""
    if region not in TAX_RATES_BP:
        raise UnknownRegionError("no tax rate for region {}".format(region))
    return percent_of(subtotal_cents, TAX_RATES_BP[region])


def compute_shipping(weight_grams: int, subtotal_cents: int, region: str) -> int:
    """Return the shipping fee; orders above the threshold ship free."""
    if region not in SHIPPING_BASE_CENTS:
        raise UnknownRegionError("no shipping rule for region {}".format(region))
    if subtotal_cents >= FREE_SHIPPING_FROM_CENTS:
        return 0
    started_kg = -(-weight_grams // 1000)
    return SHIPPING_BASE_CENTS[region] + started_kg * SHIPPING_PER_KG_CENTS


def checkout(cart: Cart, region: str) -> Receipt:
    """Compute the receipt for a cart shipped to a region."""
    if cart.is_empty():
        raise EmptyCartError("cannot check out an empty cart")
    subtotal_cents = cart.subtotal()
    return Receipt(
        subtotal_cents=subtotal_cents,
        tax_cents=compute_tax(subtotal_cents, region),
        shipping_cents=compute_shipping(cart.total_weight_grams(), subtotal_cents, region),
    )


def receipt_lines(cart: Cart, receipt: Receipt) -> list[str]:
    """Return the printable lines of a receipt."""
    lines = []
    for line in cart.lines():
        lines.append(
            "{:<24} {:>3} x {:>9} {:>10}".format(
                line.product.name,
                line.quantity,
                format_price(line.product.unit_price_cents),
                format_price(line.line_total_cents),
            )
        )
    lines.append("{:<40} {:>10}".format("Subtotal", format_price(receipt.subtotal_cents)))
    lines.append("{:<40} {:>10}".format("Tax", format_price(receipt.tax_cents)))
    lines.append("{:<40} {:>10}".format("Shipping", format_price(receipt.shipping_cents)))
    lines.append("{:<40} {:>10}".format("Total", format_price(receipt.total_cents)))
    return lines
