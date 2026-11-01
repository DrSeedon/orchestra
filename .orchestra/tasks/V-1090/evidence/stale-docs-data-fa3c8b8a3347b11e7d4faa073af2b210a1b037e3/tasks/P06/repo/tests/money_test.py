import pytest

from cartkit.errors import InvalidPriceError
from cartkit.money import format_price, parse_price, percent_of


@pytest.mark.parametrize(
    "text, expected",
    [("12", 1200), ("12.5", 1250), ("$3.99", 399), (" 0.07 ", 7)],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1.234", "-5"])
def test_parse_price_rejects_bad_input(text):
    with pytest.raises(InvalidPriceError):
        parse_price(text)


def test_format_price():
    assert format_price(1299) == "$12.99"
    assert format_price(5) == "$0.05"
    assert format_price(-250) == "-$2.50"


def test_percent_of_rounds_half_up():
    assert percent_of(1000, 725) == 73
    assert percent_of(200, 25) == 1
    assert percent_of(0, 725) == 0
