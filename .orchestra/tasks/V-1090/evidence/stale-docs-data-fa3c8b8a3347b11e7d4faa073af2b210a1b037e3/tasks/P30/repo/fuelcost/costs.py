"""Fuel use and cost of trips."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fuelcost.trips import Trip

CENT = Decimal("0.01")


def roundMoney(amount: Decimal) -> Decimal:
    """Round an amount to two digits after the point, halves away from zero."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def formatMoney(amount: Decimal) -> str:
    """Return an amount as text with two digits after the point, for example 12.30."""
    return str(roundMoney(amount))


def litresUsed(km: Decimal, consumption: Decimal) -> Decimal:
    """Return the litres used for a distance at a consumption in litres per 100 km."""
    return km * consumption / 100


def tripCost(trip: Trip, vehicles: dict[str, Decimal], settings: dict[str, Any]) -> Decimal:
    """Return the cost of a trip: fuel at the set price plus the wear charge per km."""
    consumption = vehicles.get(trip.car)
    if consumption is None:
        raise ValueError(f"trip on {trip.day.isoformat()}: unknown car {trip.car}")
    fuel = litresUsed(trip.km, consumption) * settings["price"]
    return roundMoney(fuel + trip.km * settings["wear"])
