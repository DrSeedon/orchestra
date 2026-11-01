from datetime import date
from decimal import Decimal

from meterread.readings import Reading
from meterread.settings import Settings
from meterread.usage import Usage, average_per_day, flat_cost, meter_usage

READINGS = [
    Reading("M1", date(2026, 3, 1), 1000),
    Reading("M2", date(2026, 3, 1), 40),
    Reading("M1", date(2026, 3, 11), 1125),
    Reading("M1", date(2026, 3, 31), 1300),
]


def test_meter_usage():
    usages, error = meter_usage(READINGS)
    assert error is None
    assert usages == [
        Usage("M1", date(2026, 3, 1), date(2026, 3, 31), 300),
        Usage("M2", date(2026, 3, 1), date(2026, 3, 1), 0),
    ]
    assert usages[0].days == 30


def test_meter_usage_stops_at_bad_meter():
    usages, error = meter_usage(READINGS + [Reading("M2", date(2026, 3, 2), 39)])
    assert usages is None
    assert error.startswith("meter M2:")


def test_average_per_day():
    assert average_per_day(Usage("M1", date(2026, 3, 1), date(2026, 3, 4), 10)) == Decimal("3.3")
    assert average_per_day(Usage("M2", date(2026, 3, 1), date(2026, 3, 1), 0)) is None


def test_flat_cost():
    usage = Usage("M1", date(2026, 3, 1), date(2026, 3, 31), 300)
    settings = Settings(unit_price=Decimal("0.25"), standing_charge=Decimal("0.40"))
    assert flat_cost(usage, settings) == Decimal("87.00")
