import json
from decimal import Decimal

import pytest

from couponkit.coupons import Coupon, coupon_discount, find_coupon, load_coupons
from couponkit.errors import CouponFileError, UnknownCouponError


def write_coupons(tmp_path, entries):
    path = tmp_path / "coupons.json"
    path.write_text(json.dumps({"coupons": entries}), encoding="utf-8")
    return str(path)


def test_load_coupons(tmp_path):
    coupons = load_coupons(write_coupons(tmp_path, [
        {"code": "save10", "kind": "percent", "value": "10"},
        {"code": "FIVE", "kind": "amount", "value": "5.00", "minimum": "20"},
    ]))
    assert coupons == {
        "SAVE10": Coupon("SAVE10", "percent", Decimal("10.00")),
        "FIVE": Coupon("FIVE", "amount", Decimal("5.00"), Decimal("20.00")),
    }


@pytest.mark.parametrize("entry, message", [
    ({"kind": "amount", "value": "5"}, "needs a code"),
    ({"code": "X", "kind": "gift", "value": "5"}, "kind must be one of"),
    ({"code": "X", "kind": "percent", "value": "12.5"}, "whole number"),
    ({"code": "X", "kind": "percent", "value": "120"}, "whole number"),
    ({"code": "X", "kind": "amount", "value": "five"}, "not an amount"),
])
def test_bad_coupon(tmp_path, entry, message):
    with pytest.raises(CouponFileError, match=message):
        load_coupons(write_coupons(tmp_path, [entry]))


def test_code_twice(tmp_path):
    entries = [{"code": "A", "kind": "amount", "value": "1"}, {"code": "a", "kind": "amount", "value": "2"}]
    with pytest.raises(CouponFileError, match="appears twice"):
        load_coupons(write_coupons(tmp_path, entries))


def test_find_coupon():
    coupons = {"SAVE10": Coupon("SAVE10", "percent", Decimal("10"))}
    assert find_coupon(coupons, "save10").code == "SAVE10"
    with pytest.raises(UnknownCouponError, match="unknown coupon: NOPE"):
        find_coupon(coupons, "NOPE")


def test_coupon_discount():
    percent = Coupon("SAVE15", "percent", Decimal("15"))
    assert coupon_discount(percent, Decimal("10.10")) == Decimal("1.52")
    amount = Coupon("FIVE", "amount", Decimal("5.00"), minimum=Decimal("20.00"))
    assert coupon_discount(amount, Decimal("19.99")) == Decimal("0.00")
    assert coupon_discount(amount, Decimal("20.00")) == Decimal("5.00")
    big = Coupon("BIG", "amount", Decimal("50.00"))
    assert coupon_discount(big, Decimal("30.00")) == Decimal("30.00")
