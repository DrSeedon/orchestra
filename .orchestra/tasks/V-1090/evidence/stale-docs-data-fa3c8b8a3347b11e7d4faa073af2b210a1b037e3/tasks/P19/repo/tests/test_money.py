import pytest

from shiprate.money import format_cents, parse_cents, percent_of


@pytest.mark.parametrize("text, expected", [
    ("4.90", 490), ("12", 1200), ("0.5", 50), (" 32.15 ", 3215), ("0.00", 0),
])
def test_parse_cents(text, expected):
    assert parse_cents(text) == expected


@pytest.mark.parametrize("text", ["", "-1.00", "1.234", "1,50", "abc", "1.x"])
def test_parse_cents_rejects_bad_amounts(text):
    with pytest.raises(ValueError):
        parse_cents(text)


def test_format_cents():
    assert format_cents(490) == "4.90"
    assert format_cents(5) == "0.05"
    assert format_cents(0) == "0.00"
    assert format_cents(-1205) == "-12.05"


def test_percent_of_rounds_half_up():
    assert percent_of(1000, 8) == 80
    assert percent_of(1470, 15) == 221
    assert percent_of(3215, 15) == 482
    assert percent_of(690, 0) == 0
