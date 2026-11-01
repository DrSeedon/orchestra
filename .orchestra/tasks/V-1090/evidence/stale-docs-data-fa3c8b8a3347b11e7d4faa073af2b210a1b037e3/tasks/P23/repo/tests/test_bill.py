from decimal import Decimal

import pytest

from tipjar.bill import BillItem, load_bill, subtotal


def write(tmp_path, text):
    path = tmp_path / "bill.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_bill_reads_items_and_skips_blank_rows(tmp_path):
    path = write(tmp_path, "item,amount\nsoup,4.5\n,\nbread,2.00\n")
    assert load_bill(path) == [
        BillItem("soup", Decimal("4.50")),
        BillItem("bread", Decimal("2.00")),
    ]


def test_load_bill_reports_the_line_of_a_bad_row(tmp_path):
    path = write(tmp_path, "item,amount\nsoup,4.50\nbread,two\n")
    with pytest.raises(ValueError, match=":3:"):
        load_bill(path)


def test_load_bill_needs_items(tmp_path):
    path = write(tmp_path, "item,amount\n")
    with pytest.raises(ValueError, match="no items"):
        load_bill(path)


def test_load_bill_needs_both_columns(tmp_path):
    path = write(tmp_path, "item,price\nsoup,4.50\n")
    with pytest.raises(ValueError, match="amount"):
        load_bill(path)


def test_subtotal():
    items = [BillItem("a", Decimal("1.10")), BillItem("b", Decimal("2.25"))]
    assert subtotal(items) == Decimal("3.35")
    assert subtotal([]) == Decimal("0.00")
