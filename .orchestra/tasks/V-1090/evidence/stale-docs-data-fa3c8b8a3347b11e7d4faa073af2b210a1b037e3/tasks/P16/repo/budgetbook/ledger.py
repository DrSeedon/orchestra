"""Read the household ledger: a CSV file with one transaction per row.

The file has the columns date, category, kind and amount, plus a note column
that may be missing or empty. Dates are ISO dates (2024-03-05).
"""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from budgetbook.money import parseAmount

KIND_EXPENSE = "expense"
KIND_REFUND = "refund"
KIND_INCOME = "income"
KINDS = (KIND_EXPENSE, KIND_REFUND, KIND_INCOME)

REQUIRED_COLUMNS = ("date", "category", "kind", "amount")


@dataclass
class Transaction:
    """One ledger row. The amount is always positive; kind gives its direction."""

    day: date
    category: str
    kind: str
    amount: Decimal
    note: str | None = None


def parseRow(row: dict[str, str | None], lineNo: int) -> Transaction:
    """Build a Transaction from one CSV row; lineNo is used in error messages."""
    text = {name: (row.get(name) or "").strip() for name in REQUIRED_COLUMNS + ("note",)}
    try:
        day = date.fromisoformat(text["date"])
    except ValueError:
        raise ValueError(f"line {lineNo}: bad date {text['date']!r}") from None
    category = text["category"].lower()
    if not category:
        raise ValueError(f"line {lineNo}: empty category")
    kind = text["kind"].lower()
    if kind not in KINDS:
        raise ValueError(f"line {lineNo}: unknown kind {kind!r}")
    try:
        amount = parseAmount(text["amount"])
    except ValueError as err:
        raise ValueError(f"line {lineNo}: {err}") from None
    if amount <= 0:
        raise ValueError(f"line {lineNo}: amount must be positive")
    return Transaction(day, category, kind, amount, text["note"] or None)


def loadTransactions(path: str) -> list[Transaction]:
    """Read every transaction of a ledger file, in file order."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
        missing = [name for name in REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        return [parseRow(row, lineNo) for lineNo, row in enumerate(reader, start=2)]


def monthKey(day: date) -> str:
    """Return the month of a date as YYYY-MM."""
    return f"{day.year:04d}-{day.month:02d}"


def inMonth(transactions: list[Transaction], month: str) -> list[Transaction]:
    """Keep the transactions whose date falls in month (YYYY-MM)."""
    return [t for t in transactions if monthKey(t.day) == month]
