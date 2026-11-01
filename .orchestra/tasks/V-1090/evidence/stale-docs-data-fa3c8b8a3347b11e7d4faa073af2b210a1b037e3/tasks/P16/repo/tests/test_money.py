from decimal import Decimal

import pytest

from budgetbook.money import formatAmount, parseAmount, sumAmounts


def test_parse_amount_quantizes_to_two_places():
    assert parseAmount("12.5") == Decimal("12.50")
    assert str(parseAmount(" 7 ")) == "7.00"


def test_parse_amount_accepts_thousands_separator_and_sign():
    assert parseAmount("1,250.00") == Decimal("1250.00")
    assert parseAmount("-3.10") == Decimal("-3.10")


@pytest.mark.parametrize("text", ["", "   ", "abc", "1.2.3", "nan"])
def test_parse_amount_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parseAmount(text)


def test_format_amount():
    assert formatAmount(Decimal("1250")) == "1250.00"
    assert formatAmount(Decimal("-5.1")) == "-5.10"
    assert formatAmount(-Decimal("0.00")) == "0.00"


def test_sum_amounts():
    assert sumAmounts([Decimal("0.10"), Decimal("0.20"), Decimal("-0.05")]) == Decimal("0.25")
    assert sumAmounts([]) == Decimal("0.00")
