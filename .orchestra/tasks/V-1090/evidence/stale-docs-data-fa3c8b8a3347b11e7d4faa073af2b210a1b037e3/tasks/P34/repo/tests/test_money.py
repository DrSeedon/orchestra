from decimal import Decimal

import pytest

from meterread.money import format_amount, parse_amount, round_amount


@pytest.mark.parametrize("text, expected", [("12.30", "12.30"), ("7", "7.00"), (" 0.5 ", "0.50")])
def test_parse_amount(text, expected):
    assert parse_amount(text) == (Decimal(expected), None)


@pytest.mark.parametrize("text", ["", "-1.00", "1.234", "abc", "1,50"])
def test_parse_amount_rejects(text):
    amount, error = parse_amount(text)
    assert amount is None
    assert error.startswith("not an amount")


def test_round_amount_rounds_halves_up():
    assert round_amount(Decimal("2.345")) == Decimal("2.35")
    assert round_amount(Decimal("2.344")) == Decimal("2.34")


def test_format_amount():
    assert format_amount(Decimal("12.3")) == "12.30"
    assert format_amount(Decimal("0")) == "0.00"
