"""Totals of a fund: what has been awarded and what is left."""
from grantpot.models import Award, Fund
from grantpot.money import format_cents


def awarded_total(awards: list[Award]) -> int:
    """Return the sum of all awards."""
    return sum(award.amount for award in awards)


def remaining(fund: Fund, awards: list[Award]) -> int:
    """Return the money left in the fund; it is negative when the fund is overspent."""
    return fund.budget - awarded_total(awards)


def totals_by_recipient(awards: list[Award]) -> dict[str, int]:
    """Return the total awarded to each recipient, in order of first award."""
    totals = {}
    for award in awards:
        totals[award.recipient] = totals.get(award.recipient, 0) + award.amount
    return totals


def check_award(fund: Fund, awards: list[Award], amount_cents: int) -> None:
    """Fail when an award of ``amount_cents`` is not possible."""
    if amount_cents <= 0:
        raise ValueError("an award must be more than 0.00")
    left_cents = remaining(fund, awards)
    if amount_cents > left_cents:
        raise ValueError(
            f"an award of {format_cents(amount_cents)} is more than the {format_cents(left_cents)} left")


def status_lines(fund: Fund, awards: list[Award]) -> list[str]:
    """Return the lines of the status report of a fund."""
    spent_cents = awarded_total(awards)
    lines = [
        f"fund: {fund.name}",
        f"budget: {format_cents(fund.budget)}",
        f"awarded: {format_cents(spent_cents)} in {len(awards)} awards",
        f"remaining: {format_cents(fund.budget - spent_cents)}",
    ]
    for recipient, total_cents in totals_by_recipient(awards).items():
        lines.append(f"  {recipient}: {format_cents(total_cents)}")
    return lines
