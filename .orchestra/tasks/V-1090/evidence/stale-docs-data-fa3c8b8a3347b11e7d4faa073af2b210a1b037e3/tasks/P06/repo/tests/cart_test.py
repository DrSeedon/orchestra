import pytest

from cartkit.cart import MAX_QUANTITY, Cart
from cartkit.errors import InvalidQuantityError, UnknownProductError


def test_add_merges_lines(catalog):
    cart = Cart(catalog)
    cart.add("MUG-01")
    cart.add("MUG-01", 2)
    assert [(line.product.sku, line.quantity) for line in cart.lines()] == [("MUG-01", 3)]
    assert cart.subtotal() == 3750


def test_subtotal_and_weight(catalog):
    cart = Cart(catalog)
    cart.add("TEA-02", 2)
    cart.add("KET-03")
    assert cart.subtotal() == 2 * 499 + 3900
    assert cart.total_weight_grams() == 2 * 120 + 1300


def test_quantity_limits(catalog):
    cart = Cart(catalog)
    with pytest.raises(InvalidQuantityError):
        cart.add("MUG-01", 0)
    cart.add("MUG-01", MAX_QUANTITY)
    with pytest.raises(InvalidQuantityError):
        cart.add("MUG-01")


def test_set_quantity_and_remove(catalog):
    cart = Cart(catalog)
    cart.add("TEA-02")
    cart.set_quantity("TEA-02", 5)
    assert cart.lines()[0].quantity == 5
    cart.remove("TEA-02")
    assert cart.is_empty()
    with pytest.raises(UnknownProductError):
        cart.remove("TEA-02")
