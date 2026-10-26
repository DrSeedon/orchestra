"""The cost report: one row per trip and a total row."""
import csv
from decimal import Decimal
from typing import Any

from fuelcost.costs import formatMoney, litresUsed, tripCost
from fuelcost.trips import Trip

HEADER = ("date", "car", "km", "litres", "cost")


def reportRows(trips: list[Trip], vehicles: dict[str, Decimal],
               settings: dict[str, Any]) -> list[list[str]]:
    """Return the report rows: one per trip in the given order, then the total row."""
    rows: list[list[str]] = []
    totalKm = Decimal(0)
    totalLitres = Decimal(0)
    totalCost = Decimal(0)
    for trip in trips:
        cost = tripCost(trip, vehicles, settings)
        litres = litresUsed(trip.km, vehicles[trip.car])
        rows.append([trip.day.isoformat(), trip.car, str(trip.km), formatMoney(litres),
                     formatMoney(cost)])
        totalKm += trip.km
        totalLitres += litres
        totalCost += cost
    rows.append(["total", "", str(totalKm), formatMoney(totalLitres), formatMoney(totalCost)])
    return rows


def writeReport(rows: list[list[str]], path: str) -> None:
    """Write the report rows as CSV with the header line."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
