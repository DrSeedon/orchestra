"""Read the tenants file: one row per rented unit."""
import csv
from dataclasses import dataclass
from datetime import date
from typing import Dict, List

from rentroll.money import to_cents

COLUMNS = ("unit", "name", "rent", "since")


@dataclass(frozen=True)
class Tenant:
    """The tenant of one unit. rent is the monthly rent in cents."""

    unit: str
    name: str
    rent: int
    since: date


def parse_tenant(row: Dict[str, str], line_no: int) -> Tenant:
    """Build a Tenant from one row of the tenants file."""
    unit = (row.get("unit") or "").strip()
    if not unit:
        raise ValueError(f"line {line_no}: unit is empty")
    try:
        rent_cents = to_cents(row.get("rent") or "")
        since = date.fromisoformat((row.get("since") or "").strip())
    except ValueError as exc:
        raise ValueError(f"line {line_no}: {exc}") from None
    if rent_cents <= 0:
        raise ValueError(f"line {line_no}: rent of unit {unit} must be above zero")
    return Tenant(unit=unit, name=(row.get("name") or "").strip(), rent=rent_cents, since=since)


def load_tenants(path: str) -> List[Tenant]:
    """Read a tenants CSV file with the columns unit, name, rent and since.

    The tenants come back in file order. A unit may appear only once.
    """
    tenants: List[Tenant] = []
    seen = set()
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        for line_no, row in enumerate(reader, start=2):
            tenant = parse_tenant(row, line_no)
            if tenant.unit in seen:
                raise ValueError(f"line {line_no}: unit {tenant.unit} is listed twice")
            seen.add(tenant.unit)
            tenants.append(tenant)
    return tenants


def tenants_by_unit(tenants: List[Tenant]) -> Dict[str, Tenant]:
    """Return the tenants keyed by unit."""
    return {tenant.unit: tenant for tenant in tenants}
