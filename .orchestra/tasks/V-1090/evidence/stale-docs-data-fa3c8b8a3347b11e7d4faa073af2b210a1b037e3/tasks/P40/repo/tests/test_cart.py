from decimal import Decimal

import pytest

from couponkit.cart import CartLine, cart_subtotal, load_cart
from couponkit.errors import CartError, CouponKitError


def write_cart(tmp_path, text):
    path = tmp_path / "cart.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_cart(tmp_path):
    lines = load_cart(write_cart(tmp_path, "sku,quantity,price\nTEA-01,2,12.50\nMUG-02,1,18\n"))
    assert lines == [
        CartLine(sku="TEA-01", quantity=2, price=Decimal("12.50")),
        CartLine(sku="MUG-02", quantity=1, price=Decimal("18.00")),
    ]
    assert lines[0].total == Decimal("25.00")
    assert cart_subtotal(lines) == Decimal("43.00")


def test_empty_cart_subtotal():
    assert cart_subtotal([]) == Decimal("0.00")


def test_missing_column(tmp_path):
    with pytest.raises(CartError, match="missing column price"):
        load_cart(write_cart(tmp_path, "sku,quantity\nTEA-01,2\n"))


@pytest.mark.parametrize("row, message", [
    (",2,12.50", "sku is empty"),
    ("TEA-01,0,12.50", "quantity"),
    ("TEA-01,two,12.50", "quantity"),
    ("TEA-01,2,12.5x", "not an amount"),
])
def test_bad_row(tmp_path, row, message):
    with pytest.raises(CartError, match="line 2: " + message):
        load_cart(write_cart(tmp_path, "sku,quantity,price\n" + row + "\n"))


def test_cart_error_is_a_couponkit_error():
    assert issubclass(CartError, CouponKitError)
