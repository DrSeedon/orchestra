"""Read the ledger: charges, payments and credits per unit."""
import csv
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List

from rentroll.money import to_cents

COLUMNS = ("date", "unit", "kind", "amount")


class EntryKind(Enum):
    """What a ledger line does to the balance of a unit."""

    CHARGE = "charge"
    PAYMENT = "payment"
    CREDIT = "credit"


@dataclass(frozen=True)
class LedgerEntry:
    """One ledger line. amount is in cents and always above zero."""

    day: date
    unit: str
    kind: EntryKind
    amount: int


def parse_entry(row: Dict[str, str], line_no: int) -> LedgerEntry:
    """Build a LedgerEntry from one row of the ledger file."""
    unit = (row.get("unit") or "").strip()
    if not unit:
        raise ValueError(f"line {line_no}: unit is empty")
    try:
        day = date.fromisoformat((row.get("date") or "").strip())
        kind = EntryKind((row.get("kind") or "").strip().lower())
        amount_cents = to_cents(row.get("amount") or "")
    except ValueError as exc:
        raise ValueError(f"line {line_no}: {exc}") from None
    if amount_cents <= 0:
        raise ValueError(f"line {line_no}: amount must be above zero")
    return LedgerEntry(day=day, unit=unit, kind=kind, amount=amount_cents)


def load_ledger(path: str) -> List[LedgerEntry]:
    """Read a ledger CSV file with the columns date, unit, kind and amount.

    The entries come back in file order.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        return [parse_entry(row, line_no) for line_no, row in enumerate(reader, start=2)]


def signed_amount(entry: LedgerEntry) -> int:
    """Return the effect of an entry on the balance: charges add, payments and credits subtract."""
    if entry.kind is EntryKind.CHARGE:
        return entry.amount
    return -entry.amount


def balances(entries: List[LedgerEntry]) -> Dict[str, int]:
    """Return the balance in cents of every unit that appears in the entries."""
    totals: Dict[str, int] = {}
    for entry in entries:
        totals[entry.unit] = totals.get(entry.unit, 0) + signed_amount(entry)
    return totals
