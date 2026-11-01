import pytest

from cartkit.cart import Cart
from cartkit.checkout import checkout, compute_shipping, compute_tax, receipt_lines
from cartkit.errors import EmptyCartError, UnknownRegionError


def test_compute_tax():
    assert compute_tax(10000, "CA") == 725
    assert compute_tax(10000, "OR") == 0
    with pytest.raises(UnknownRegionError):
        compute_tax(10000, "ZZ")


def test_compute_shipping_per_started_kilogram():
    assert compute_shipping(400, 1000, "CA") == 499 + 150
    assert compute_shipping(1300, 1000, "CA") == 499 + 2 * 150


def test_free_shipping_above_threshold():
    assert compute_shipping(5000, 7500, "NY") == 0


def test_checkout_totals(catalog):
    cart = Cart(catalog)
    cart.add("MUG-01", 2)
    receipt = checkout(cart, "TX")
    assert receipt.subtotal_cents == 2500
    assert receipt.tax_cents == 156
    assert receipt.shipping_cents == 549 + 150
    assert receipt.total_cents == 2500 + 156 + 699


def test_checkout_empty_cart(catalog):
    with pytest.raises(EmptyCartError):
        checkout(Cart(catalog), "CA")


def test_receipt_lines(catalog):
    cart = Cart(catalog)
    cart.add("TEA-02", 3)
    lines = receipt_lines(cart, checkout(cart, "OR"))
    assert lines[0].startswith("Green tea")
    assert lines[0].endswith("$14.97")
    assert lines[-1].startswith("Total")
    assert lines[-1].endswith("$21.46")
