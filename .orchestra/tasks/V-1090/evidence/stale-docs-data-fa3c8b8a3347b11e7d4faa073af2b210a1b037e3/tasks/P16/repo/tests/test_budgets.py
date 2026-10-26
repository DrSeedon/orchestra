from datetime import date
from decimal import Decimal

import pytest

from budgetbook.budgets import budgetFor, loadBudgets
from budgetbook.ledger import KIND_EXPENSE, KIND_INCOME, KIND_REFUND, Transaction
from budgetbook.summary import incomeTotal, signedAmount, spentByCategory


def writeBudgets(folder, text):
    target = folder / "budgets.csv"
    target.write_text(text, encoding="utf-8")
    return str(target)


def test_load_budgets(tmp_path):
    budgets = loadBudgets(writeBudgets(tmp_path, "category,limit\nGroceries,250\nrent,900.00\n"))
    assert budgets == {"groceries": Decimal("250.00"), "rent": Decimal("900.00")}
    assert budgetFor(budgets, " Rent ") == Decimal("900.00")
    assert budgetFor(budgets, "travel") is None


@pytest.mark.parametrize("text, message", [
    ("category,amount\nfun,10\n", "category,limit"),
    ("category,limit\nfun,10\nFun,20\n", "duplicate"),
    ("category,limit\nfun,-1\n", "negative"),
    ("category,limit\n,5\n", "empty category"),
])
def test_load_budgets_rejects_bad_files(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        loadBudgets(writeBudgets(tmp_path, text))


def makeTransaction(category, kind, amount):
    return Transaction(date(2024, 3, 1), category, kind, Decimal(amount))


def test_signed_amount():
    assert signedAmount(makeTransaction("fun", KIND_EXPENSE, "4.00")) == Decimal("4.00")
    assert signedAmount(makeTransaction("fun", KIND_REFUND, "1.50")) == Decimal("-1.50")
    assert signedAmount(makeTransaction("salary", KIND_INCOME, "100.00")) is None


def test_spent_by_category_nets_refunds_and_skips_income():
    transactions = [
        makeTransaction("rent", KIND_EXPENSE, "900.00"),
        makeTransaction("fun", KIND_EXPENSE, "20.00"),
        makeTransaction("fun", KIND_REFUND, "5.25"),
        makeTransaction("salary", KIND_INCOME, "2000.00"),
    ]
    assert spentByCategory(transactions) == {"fun": Decimal("14.75"), "rent": Decimal("900.00")}
    assert list(spentByCategory(transactions)) == ["fun", "rent"]
    assert incomeTotal(transactions) == Decimal("2000.00")
