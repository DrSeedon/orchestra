import pytest

from pricewatch.money import averageCents, formatCents, parseCents


@pytest.mark.parametrize("text, expected", [
    ("12.30", 1230),
    ("7", 700),
    ("0.5", 50),
    (" 3.05 ", 305),
    ("-1.20", -120),
])
def test_parse_amounts(text, expected):
    assert parseCents(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1.234", "1,20", "12."])
def test_parse_rejects_bad_text(text):
    with pytest.raises(ValueError, match="not an amount"):
        parseCents(text)


def test_format_amounts():
    assert formatCents(1230) == "12.30"
    assert formatCents(5) == "0.05"
    assert formatCents(-55) == "-0.55"
    assert formatCents(0) == "0.00"


def test_average_rounds_half_up():
    assert averageCents([100, 101]) == 101
    assert averageCents([100, 100, 101]) == 100


def test_average_of_nothing_fails():
    with pytest.raises(ValueError):
        averageCents([])
