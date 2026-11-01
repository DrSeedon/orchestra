from decimal import Decimal

import pytest

from tipjar.tips import parse_percent, tip_amount, total_with_tip


def test_parse_percent_accepts_a_percent_sign():
    assert parse_percent("15") == 15
    assert parse_percent(" 15% ") == 15
    assert parse_percent("0") == 0


def test_parse_percent_without_text_means_no_tip():
    assert parse_percent(None) is None
    assert parse_percent("  ") is None


@pytest.mark.parametrize("text", ["abc", "-5", "12.5", "101"])
def test_parse_percent_rejects_bad_values(text):
    with pytest.raises(ValueError):
        parse_percent(text)


def test_tip_and_total():
    tip = tip_amount(Decimal("54.50"), 15)
    assert tip == Decimal("8.18")
    assert total_with_tip(Decimal("54.50"), tip) == Decimal("62.68")


def test_no_tip_keeps_the_subtotal():
    assert tip_amount(Decimal("54.50"), None) is None
    assert total_with_tip(Decimal("54.50"), None) == Decimal("54.50")
