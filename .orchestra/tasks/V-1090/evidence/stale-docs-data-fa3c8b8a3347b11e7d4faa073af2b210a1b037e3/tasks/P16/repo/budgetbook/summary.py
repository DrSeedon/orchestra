"""Spending and income totals for a list of transactions."""

from collections.abc import Iterable
from decimal import Decimal

from budgetbook.ledger import KIND_EXPENSE, KIND_INCOME, KIND_REFUND, Transaction
from budgetbook.money import sumAmounts


def signedAmount(transaction: Transaction) -> Decimal | None:
    """Return the effect on spending: expenses add, refunds subtract, income is None."""
    if transaction.kind == KIND_EXPENSE:
        return transaction.amount
    if transaction.kind == KIND_REFUND:
        return -transaction.amount
    return None


def spentByCategory(transactions: Iterable[Transaction]) -> dict[str, Decimal]:
    """Net spending per category, sorted by category name."""
    grouped: dict[str, list[Decimal]] = {}
    for transaction in transactions:
        value = signedAmount(transaction)
        if value is None:
            continue
        grouped.setdefault(transaction.category, []).append(value)
    return {category: sumAmounts(values) for category, values in sorted(grouped.items())}


def incomeTotal(transactions: Iterable[Transaction]) -> Decimal:
    """Sum of all income transactions."""
    return sumAmounts(t.amount for t in transactions if t.kind == KIND_INCOME)
