"""Employee records and the employee registry."""

from dataclasses import dataclass
from decimal import Decimal

from payrun.money import parseAmount

MAX_PENSION_RATE = Decimal("0.15")


@dataclass(frozen=True)
class Employee:
    """One employee on the hourly payroll."""

    employeeId: str
    name: str
    hourlyRate: Decimal
    pensionRate: Decimal


def parseEmployee(line: str) -> Employee:
    """Parse ``id,name,hourly_rate,pension_rate`` (pension rate as a fraction)."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 4:
        raise ValueError(f"expected 4 fields, got {len(parts)}: {line!r}")
    employeeId, name, rateText, pensionText = parts
    if not employeeId or not name:
        raise ValueError(f"missing id or name: {line!r}")
    rate = parseAmount(rateText)
    if rate <= 0:
        raise ValueError(f"hourly rate must be positive: {line!r}")
    pension = Decimal(pensionText)
    if not Decimal("0") <= pension <= MAX_PENSION_RATE:
        raise ValueError(f"pension rate out of range: {line!r}")
    return Employee(employeeId, name, rate, pension)


def loadRegistry(lines: list[str]) -> dict[str, Employee]:
    """Build the registry from employee lines; blank lines and ``#`` comments are skipped."""
    registry: dict[str, Employee] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        employee = parseEmployee(line)
        if employee.employeeId in registry:
            raise ValueError(f"duplicate employee id {employee.employeeId}")
        registry[employee.employeeId] = employee
    return registry


def readRegistry(path: str) -> dict[str, Employee]:
    """Load the registry from a text file with one employee per line."""
    with open(path, encoding="utf-8") as handle:
        return loadRegistry(handle.read().splitlines())


def findEmployee(registry: dict[str, Employee], employeeId: str) -> Employee:
    """Return the employee with ``employeeId``."""
    try:
        return registry[employeeId]
    except KeyError:
        raise KeyError(f"unknown employee {employeeId}") from None
