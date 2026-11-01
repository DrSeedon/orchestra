import pytest

from grantpot.money import format_cents, parse_cents


@pytest.mark.parametrize("text, cents", [("12.30", 1230), ("12.3", 1230), ("12", 1200),
                                         (" 0.05 ", 5), ("1500.00", 150000)])
def test_parse_cents(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "1.234", "-5.00", "1,000.00", "12."])
def test_parse_cents_rejects_bad_text(text):
    with pytest.raises(ValueError, match="not an amount"):
        parse_cents(text)


@pytest.mark.parametrize("cents, text", [(1230, "12.30"), (5, "0.05"), (0, "0.00"), (-250, "-2.50")])
def test_format_cents(cents, text):
    assert format_cents(cents) == text
