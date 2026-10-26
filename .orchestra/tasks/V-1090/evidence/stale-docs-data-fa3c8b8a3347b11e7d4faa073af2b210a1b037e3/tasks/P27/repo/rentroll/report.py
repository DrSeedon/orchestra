"""Build and write the rent roll: one line per tenant with charges, payments and balance."""
import csv
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from rentroll.ledger import EntryKind, LedgerEntry
from rentroll.money import format_cents
from rentroll.tenants import Tenant

HEADER = ("unit", "tenant", "rent", "charged", "paid", "balance")


class SortOrder(Enum):
    """Order of the lines in the rent roll."""

    UNIT = "unit"
    BALANCE = "balance"


@dataclass
class RollLine:
    """One line of the rent roll. All amounts are in cents."""

    unit: str
    tenant: str
    rent: int
    charged: int = 0
    paid: int = 0

    @property
    def balance(self) -> int:
        """What the tenant owes: charges minus payments and credits."""
        return self.charged - self.paid


def rent_roll(tenants: List[Tenant], entries: List[LedgerEntry],
              order: SortOrder = SortOrder.UNIT) -> List[RollLine]:
    """Return one rent roll line per tenant.

    Payments and credits both count as paid. Entries of units without a tenant are left out.
    """
    lines: Dict[str, RollLine] = {
        tenant.unit: RollLine(unit=tenant.unit, tenant=tenant.name, rent=tenant.rent)
        for tenant in tenants
    }
    for entry in entries:
        line = lines.get(entry.unit)
        if line is None:
            continue
        if entry.kind is EntryKind.CHARGE:
            line.charged += entry.amount
        else:
            line.paid += entry.amount
    rows = list(lines.values())
    if order is SortOrder.BALANCE:
        rows.sort(key=lambda line: (-line.balance, line.unit))
    else:
        rows.sort(key=lambda line: line.unit)
    return rows


def roll_row(line: RollLine) -> List[str]:
    """Return the CSV cells of one rent roll line."""
    amounts = [line.rent, line.charged, line.paid, line.balance]
    return [line.unit, line.tenant] + [format_cents(amount_cents) for amount_cents in amounts]


def write_rent_roll(lines: List[RollLine], path: str) -> None:
    """Write the rent roll as CSV, with a closing total line for the balance."""
    total_cents = sum(line.balance for line in lines)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for line in lines:
            writer.writerow(roll_row(line))
        writer.writerow(["total", "", "", "", "", format_cents(total_cents)])
