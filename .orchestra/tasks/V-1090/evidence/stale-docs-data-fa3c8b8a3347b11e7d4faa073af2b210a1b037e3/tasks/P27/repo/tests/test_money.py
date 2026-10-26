import pytest

from rentroll.money import format_cents, to_cents


@pytest.mark.parametrize("text, expected", [
    ("1250", 125000),
    ("1250.5", 125050),
    ("1250.05", 125005),
    (" 0.99 ", 99),
    ("-12.30", -1230),
])
def test_to_cents(text, expected):
    assert to_cents(text) == expected


@pytest.mark.parametrize("text", ["", "12.345", "12,50", "abc", "1.2.3"])
def test_to_cents_rejects_bad_amounts(text):
    with pytest.raises(ValueError):
        to_cents(text)


def test_format_cents():
    assert format_cents(125000) == "1250.00"
    assert format_cents(5) == "0.05"
    assert format_cents(0) == "0.00"
    assert format_cents(-1230) == "-12.30"
