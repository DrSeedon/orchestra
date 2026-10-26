"""Monthly spending report per category.

Usage: python -m budgetbook.report LEDGER MONTH OUTPUT [--budgets FILE]
"""

import argparse
import csv
import re
import sys
from decimal import Decimal

from budgetbook.budgets import budgetFor, loadBudgets
from budgetbook.ledger import inMonth, loadTransactions
from budgetbook.money import formatAmount
from budgetbook.summary import incomeTotal, spentByCategory

MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
HEADER = ("category", "spent", "budget", "remaining")


def isMonth(text: str) -> bool:
    """True when text is a month written as YYYY-MM."""
    return MONTH_PATTERN.fullmatch(text) is not None


def reportRows(spent: dict[str, Decimal], budgets: dict[str, Decimal] | None = None) -> list[list[str]]:
    """One row per category that has spending or a budget, sorted by category."""
    names = set(spent) | set(budgets or {})
    rows = []
    for category in sorted(names):
        amount = spent.get(category, Decimal("0.00"))
        limit = budgetFor(budgets, category) if budgets is not None else None
        if limit is None:
            rows.append([category, formatAmount(amount), "", ""])
        else:
            rows.append([category, formatAmount(amount), formatAmount(limit), formatAmount(limit - amount)])
    return rows


def writeReport(path: str, rows: list[list[str]]) -> None:
    """Write the report rows as CSV with a header line."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)


def parseArgs(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m budgetbook.report",
                                     description="Write the spending per category for one month.")
    parser.add_argument("ledger", help="ledger CSV file")
    parser.add_argument("month", help="month as YYYY-MM")
    parser.add_argument("output", help="CSV file to write")
    parser.add_argument("--budgets", help="budget CSV file (category,limit)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parseArgs(argv)
    if not isMonth(args.month):
        print(f"error: month must look like 2024-03, got {args.month!r}", file=sys.stderr)
        return 2
    try:
        transactions = loadTransactions(args.ledger)
        budgets = loadBudgets(args.budgets) if args.budgets else None
    except (OSError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    selected = inMonth(transactions, args.month)
    rows = reportRows(spentByCategory(selected), budgets)
    writeReport(args.output, rows)
    print(f"{args.month}: {len(rows)} categories, income {formatAmount(incomeTotal(selected))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
