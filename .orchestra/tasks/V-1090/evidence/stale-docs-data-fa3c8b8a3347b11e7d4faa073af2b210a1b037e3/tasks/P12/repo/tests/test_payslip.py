from decimal import Decimal

import pytest

from payrun.deductions import incomeTax, pensionContribution
from payrun.employees import Employee
from payrun.payslip import buildPayslip, formatPayslip, grossPay

ANA = Employee("E01", "Ana Silva", Decimal("20.00"), Decimal("0.05"))


def test_gross_without_overtime():
    assert grossPay(ANA, Decimal("38")) == Decimal("760.00")


def test_gross_with_overtime():
    assert grossPay(ANA, Decimal("42")) == Decimal("860.00")


def test_negative_hours():
    with pytest.raises(ValueError):
        grossPay(ANA, Decimal("-1"))


@pytest.mark.parametrize(
    "gross,tax",
    [("200.00", "0.00"), ("300.00", "10.00"), ("1200.00", "230.00")],
)
def test_income_tax_bands(gross, tax):
    assert incomeTax(Decimal(gross)) == Decimal(tax)


def test_pension():
    assert pensionContribution(Decimal("860.00"), Decimal("0.05")) == Decimal("43.00")


def test_payslip_net():
    slip = buildPayslip(ANA, Decimal("42"))
    assert slip.deductions == {"tax": Decimal("122.00"), "pension": Decimal("43.00")}
    assert slip.net == Decimal("695.00")


def test_format_payslip():
    text = formatPayslip(buildPayslip(ANA, Decimal("42")))
    assert text.splitlines()[0] == "Ana Silva (E01)"
    assert "net          695.00" in text
