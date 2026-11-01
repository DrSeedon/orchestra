from datetime import date
from decimal import Decimal

import pytest

from budgetbook.ledger import KIND_EXPENSE, KIND_REFUND, inMonth, loadTransactions, monthKey, parseRow

LEDGER = (
    "date,category,kind,amount,note\n"
    "2024-03-02,Groceries,expense,12.50,\n"
    "2024-03-04,groceries,refund,2.00,bottle deposit\n"
    "2024-04-01,rent,expense,900,\n"
)


def writeFile(folder, name, text):
    target = folder / name
    target.write_text(text, encoding="utf-8")
    return str(target)


def test_load_transactions_reads_rows_in_order(tmp_path):
    rows = loadTransactions(writeFile(tmp_path, "ledger.csv", LEDGER))
    assert [t.category for t in rows] == ["groceries", "groceries", "rent"]
    assert rows[0].day == date(2024, 3, 2)
    assert rows[0].kind == KIND_EXPENSE
    assert rows[0].amount == Decimal("12.50")
    assert rows[0].note is None
    assert rows[1].kind == KIND_REFUND
    assert rows[1].note == "bottle deposit"


def test_note_column_may_be_missing(tmp_path):
    rows = loadTransactions(writeFile(tmp_path, "ledger.csv",
                                      "date,category,kind,amount\n2024-01-01,fun,expense,5\n"))
    assert rows[0].note is None


def test_missing_column_is_reported(tmp_path):
    with pytest.raises(ValueError, match="missing columns amount"):
        loadTransactions(writeFile(tmp_path, "ledger.csv", "date,category,kind\n"))


@pytest.mark.parametrize("row, message", [
    ({"date": "2024-02-30", "category": "x", "kind": "expense", "amount": "1"}, "bad date"),
    ({"date": "2024-02-01", "category": "", "kind": "expense", "amount": "1"}, "empty category"),
    ({"date": "2024-02-01", "category": "x", "kind": "gift", "amount": "1"}, "unknown kind"),
    ({"date": "2024-02-01", "category": "x", "kind": "expense", "amount": "0"}, "positive"),
    ({"date": "2024-02-01", "category": "x", "kind": "expense", "amount": "ten"}, "not an amount"),
])
def test_parse_row_errors_name_the_line(row, message):
    with pytest.raises(ValueError, match=message) as info:
        parseRow(row, 7)
    assert "line 7" in str(info.value)


def test_month_filter(tmp_path):
    rows = loadTransactions(writeFile(tmp_path, "ledger.csv", LEDGER))
    assert monthKey(date(2024, 3, 9)) == "2024-03"
    assert [t.category for t in inMonth(rows, "2024-04")] == ["rent"]
    assert inMonth(rows, "2023-03") == []
