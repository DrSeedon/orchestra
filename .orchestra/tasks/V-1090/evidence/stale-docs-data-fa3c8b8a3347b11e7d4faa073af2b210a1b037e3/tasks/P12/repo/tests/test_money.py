from decimal import Decimal

import pytest

from payrun.money import formatMoney, parseAmount, roundMoney, sumMoney


def test_parse_plain_and_grouped():
    assert parseAmount("1250.50") == Decimal("1250.50")
    assert parseAmount(" 1,250.5 ") == Decimal("1250.5")


@pytest.mark.parametrize("text", ["", "abc", "12.345"])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parseAmount(text)


def test_round_half_up():
    assert roundMoney(Decimal("2.345")) == Decimal("2.35")
    assert roundMoney(Decimal("-2.345")) == Decimal("-2.35")


def test_format():
    assert formatMoney(Decimal("1234567.8")) == "1,234,567.80"


def test_sum():
    assert sumMoney([Decimal("0.10"), Decimal("0.20")]) == Decimal("0.30")
    assert sumMoney([]) == Decimal("0.00")
