"""Read a bill: one row per item with its amount."""
import csv
from dataclasses import dataclass
from decimal import Decimal

from .money import parse_amount

BILL_COLUMNS = ("item", "amount")


@dataclass
class BillItem:
    """One item of the bill."""

    name: str
    amount: Decimal


def load_bill(path: str) -> list[BillItem]:
    """Read a bill CSV file with the header item,amount.

    Rows with an empty item and amount are skipped. Raises ValueError, with the
    line number, for a bad row and when the bill has no items. Errors from opening
    the file (OSError) are passed on to the caller.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in BILL_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("{}: missing columns {}".format(path, ", ".join(missing)))
        items = []
        for row in reader:
            name = (row["item"] or "").strip()
            amount = (row["amount"] or "").strip()
            if not name and not amount:
                continue
            if not name:
                raise ValueError("{}:{}: item without a name".format(path, reader.line_num))
            try:
                items.append(BillItem(name, parse_amount(amount)))
            except ValueError as error:
                raise ValueError("{}:{}: {}".format(path, reader.line_num, error)) from None
    if not items:
        raise ValueError("{}: the bill has no items".format(path))
    return items


def subtotal(items: list[BillItem]) -> Decimal:
    """Add up the amounts of all items."""
    return sum((item.amount for item in items), Decimal("0.00"))
