from decimal import Decimal

import pytest

from tipjar.money import format_amount, parse_amount, percent_of, round_amount, round_down


def test_parse_amount_pads_to_two_places():
    assert parse_amount("12.5") == Decimal("12.50")
    assert parse_amount(" 7 ") == Decimal("7.00")


@pytest.mark.parametrize("text", ["", "abc", "-1.00", "1.005", "nan"])
def test_parse_amount_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_rounding():
    assert round_amount(Decimal("8.175")) == Decimal("8.18")
    assert round_down(Decimal("17.909")) == Decimal("17.90")


def test_percent_of_rounds_half_up():
    assert percent_of(Decimal("54.50"), 15) == Decimal("8.18")
    assert percent_of(Decimal("10.00"), 0) == Decimal("0.00")


def test_format_amount():
    assert format_amount(Decimal("12.3")) == "12.30"
    assert format_amount(Decimal("0")) == "0.00"
