"""Income tax and pension deductions for one pay period (weekly)."""

from decimal import Decimal

from payrun.money import ZERO, roundMoney

# (upper bound of band, rate); the last band has no upper bound.
TAX_BANDS = [
    (Decimal("250.00"), Decimal("0.00")),
    (Decimal("1000.00"), Decimal("0.20")),
    (None, Decimal("0.40")),
]


def incomeTax(gross: Decimal) -> Decimal:
    """Weekly income tax on ``gross`` using the banded rates."""
    if gross < 0:
        raise ValueError("gross pay cannot be negative")
    tax = ZERO
    lower = ZERO
    for upper, rate in TAX_BANDS:
        top = gross if upper is None else min(gross, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or gross <= upper:
            break
        lower = upper
    return roundMoney(tax)


def pensionContribution(gross: Decimal, rate: Decimal) -> Decimal:
    """Employee pension contribution for the period."""
    if rate < 0:
        raise ValueError("pension rate cannot be negative")
    return roundMoney(gross * rate)


def totalDeductions(gross: Decimal, pensionRate: Decimal) -> dict[str, Decimal]:
    """All deductions for one period, keyed by name."""
    return {
        "tax": incomeTax(gross),
        "pension": pensionContribution(gross, pensionRate),
    }
