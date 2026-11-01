from decimal import Decimal

import pytest

from couponkit.errors import AmountError
from couponkit.money import format_amount, parse_amount, round_amount


def test_parse_amount():
    assert parse_amount("12.3") == Decimal("12.30")
    assert parse_amount(" 7 ") == Decimal("7.00")


@pytest.mark.parametrize("text", ["", "-1.00", "1.234", "12,30", "abc"])
def test_bad_amount(text):
    with pytest.raises(AmountError):
        parse_amount(text)


def test_round_half_up():
    assert round_amount(Decimal("2.345")) == Decimal("2.35")
    assert round_amount(Decimal("2.344")) == Decimal("2.34")


def test_format_amount():
    assert format_amount(Decimal("5")) == "5.00"
    assert format_amount(Decimal("19.999")) == "20.00"
