"""Monthly budget limits per category, read from a CSV file (category,limit)."""

import csv
from decimal import Decimal

from budgetbook.money import parseAmount


def loadBudgets(path: str) -> dict[str, Decimal]:
    """Read the budget file and return the monthly limit per category."""
    budgets: dict[str, Decimal] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
        if "category" not in columns or "limit" not in columns:
            raise ValueError(f"{path}: expected the columns category,limit")
        for lineNo, row in enumerate(reader, start=2):
            category = (row["category"] or "").strip().lower()
            if not category:
                raise ValueError(f"{path}:{lineNo}: empty category")
            if category in budgets:
                raise ValueError(f"{path}:{lineNo}: duplicate budget for {category}")
            limit = parseAmount(row["limit"] or "")
            if limit < 0:
                raise ValueError(f"{path}:{lineNo}: negative limit for {category}")
            budgets[category] = limit
    return budgets


def budgetFor(budgets: dict[str, Decimal], category: str) -> Decimal | None:
    """Return the limit of a category, or None when it has no budget."""
    return budgets.get(category.strip().lower())
