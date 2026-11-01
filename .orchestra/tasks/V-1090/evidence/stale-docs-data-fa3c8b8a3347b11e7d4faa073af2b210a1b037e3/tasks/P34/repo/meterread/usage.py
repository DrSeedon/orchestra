"""Energy used per meter and its price at a flat unit price."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from meterread.money import round_amount
from meterread.readings import Reading, check_meter, group_by_meter
from meterread.settings import Settings


@dataclass(frozen=True)
class Usage:
    """The energy a meter used from its first to its last reading."""

    meter: str
    first: date
    last: date
    kwh: int

    @property
    def days(self) -> int:
        """Number of days from the first to the last reading."""
        return (self.last - self.first).days


def meter_usage(readings: list[Reading]) -> tuple[list[Usage] | None, str | None]:
    """Work out the usage of every meter. A meter with one reading used 0 kWh in 0 days.

    :param readings: readings of any meters, in any order
    :returns: the usage per meter in order of first appearance and None,
        or None and an error message
    """
    result = []
    for meter, items in group_by_meter(readings).items():
        error = check_meter(items)
        if error:
            return None, error
        result.append(Usage(meter, items[0].day, items[-1].day, items[-1].kwh - items[0].kwh))
    return result, None


def average_per_day(usage: Usage) -> Decimal | None:
    """Average kWh per day, with one place.

    :param usage: the usage of one meter
    :returns: the average, or None when the readings span no full day
    """
    if usage.days == 0:
        return None
    return (Decimal(usage.kwh) / usage.days).quantize(Decimal("0.1"))


def flat_cost(usage: Usage, settings: Settings) -> Decimal:
    """Price the usage at the unit price, plus the standing charge for each day.

    :param usage: the usage of one meter
    :param settings: the prices
    :returns: the cost, rounded to two places
    """
    energy = usage.kwh * settings.unit_price
    standing = usage.days * settings.standing_charge
    return round_amount(energy + standing)
