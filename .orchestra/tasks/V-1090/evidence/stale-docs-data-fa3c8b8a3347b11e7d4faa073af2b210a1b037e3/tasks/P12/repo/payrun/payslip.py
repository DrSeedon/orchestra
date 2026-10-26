"""Build and print payslips."""

from dataclasses import dataclass, field
from decimal import Decimal

from payrun.deductions import totalDeductions
from payrun.employees import Employee
from payrun.money import formatMoney, roundMoney, sumMoney

STANDARD_HOURS = Decimal("40")
OVERTIME_FACTOR = Decimal("1.5")


@dataclass
class Payslip:
    """Pay for one employee and one period."""

    employee: Employee
    hours: Decimal
    gross: Decimal
    deductions: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        """Gross pay minus all deductions."""
        return roundMoney(self.gross - sumMoney(list(self.deductions.values())))


def grossPay(employee: Employee, hours: Decimal) -> Decimal:
    """Gross pay; hours above the standard week are paid at the overtime factor."""
    if hours < 0:
        raise ValueError("hours cannot be negative")
    regular = min(hours, STANDARD_HOURS)
    overtime = max(hours - STANDARD_HOURS, Decimal("0"))
    return roundMoney(employee.hourlyRate * (regular + overtime * OVERTIME_FACTOR))


def buildPayslip(employee: Employee, hours: Decimal) -> Payslip:
    """Compute gross pay and deductions for one employee."""
    gross = grossPay(employee, hours)
    return Payslip(employee, hours, gross, totalDeductions(gross, employee.pensionRate))


def formatPayslip(slip: Payslip) -> str:
    """Render a payslip as aligned text lines."""
    lines = [
        f"{slip.employee.name} ({slip.employee.employeeId})",
        f"  hours    {slip.hours:>10}",
        f"  gross    {formatMoney(slip.gross):>10}",
    ]
    for name, amount in slip.deductions.items():
        lines.append(f"  {name:<8} {formatMoney(-amount):>10}")
    lines.append(f"  net      {formatMoney(slip.net):>10}")
    return "\n".join(lines)
