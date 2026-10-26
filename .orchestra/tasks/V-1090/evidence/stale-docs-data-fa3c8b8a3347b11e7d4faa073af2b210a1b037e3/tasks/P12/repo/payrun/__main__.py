"""Weekly pay run: ``python -m payrun REGISTRY HOURS OUTPUT``.

HOURS has one ``employee id,hours worked`` line per employee. The payslips are
written to OUTPUT in the order of the hours file.
"""

import argparse
import sys
from decimal import Decimal, InvalidOperation

from payrun.employees import Employee, findEmployee, readRegistry
from payrun.money import sumMoney
from payrun.payslip import Payslip, buildPayslip, formatPayslip


def parseHours(line: str) -> tuple[str, Decimal]:
    """Parse one ``employee id,hours worked`` line."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2 or not parts[0]:
        raise ValueError(f"expected employee id and hours: {line!r}")
    try:
        hours = Decimal(parts[1])
    except InvalidOperation:
        raise ValueError(f"not a number of hours: {line!r}") from None
    return parts[0], hours


def readHours(path: str) -> list[tuple[str, Decimal]]:
    """Read the hours file; blank lines and ``#`` comments are skipped."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    return [
        parseHours(line) for line in lines if line.strip() and not line.lstrip().startswith("#")
    ]


def runPayroll(registry: dict[str, Employee], hours: list[tuple[str, Decimal]]) -> list[Payslip]:
    """Build one payslip per hours entry, in the given order."""
    return [
        buildPayslip(findEmployee(registry, employeeId), worked) for employeeId, worked in hours
    ]


def main(argv: list[str] | None = None) -> int:
    """Run the weekly payroll and return the exit status."""
    parser = argparse.ArgumentParser(prog="payrun", description="Write the payslips of one week.")
    parser.add_argument("registry", help="employee registry file")
    parser.add_argument("hours", help="hours worked, one 'employee id,hours' line per employee")
    parser.add_argument("output", help="file to write the payslips to")
    args = parser.parse_args(argv)
    try:
        registry = readRegistry(args.registry)
        slips = runPayroll(registry, readHours(args.hours))
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(formatPayslip(slip) for slip in slips) + "\n")
    netTotal = sumMoney([slip.net for slip in slips])
    print(f"wrote {len(slips)} payslips to {args.output}, net total {netTotal:,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
