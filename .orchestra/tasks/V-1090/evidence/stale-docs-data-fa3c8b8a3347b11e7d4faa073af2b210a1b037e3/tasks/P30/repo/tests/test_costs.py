import unittest
from datetime import date
from decimal import Decimal

from fuelcost.costs import formatMoney, litresUsed, roundMoney, tripCost
from fuelcost.settings import DEFAULTS
from fuelcost.trips import Trip

VEHICLES = {"polo": Decimal("5.4"), "transit": Decimal("8.9")}


def makeTrip(car="polo", km="100"):
    return Trip(date(2026, 9, 1), car, Decimal(km), "Mia", ("Tom",))


class TestMoney(unittest.TestCase):
    def testRoundMoney(self):
        self.assertEqual(roundMoney(Decimal("4.0145")), Decimal("4.01"))
        self.assertEqual(roundMoney(Decimal("8.7875")), Decimal("8.79"))
        self.assertEqual(roundMoney(Decimal("2.005")), Decimal("2.01"))

    def testFormatMoney(self):
        self.assertEqual(formatMoney(Decimal("12.3")), "12.30")
        self.assertEqual(formatMoney(Decimal("0")), "0.00")


class TestTripCost(unittest.TestCase):
    def testLitresUsed(self):
        self.assertEqual(litresUsed(Decimal("250"), Decimal("5.4")), Decimal("13.5"))

    def testCostWithDefaults(self):
        self.assertEqual(tripCost(makeTrip(), VEHICLES, DEFAULTS), Decimal("9.99"))

    def testCostWithWear(self):
        settings = dict(DEFAULTS, price=Decimal("2.00"), wear=Decimal("0.05"))
        self.assertEqual(tripCost(makeTrip("transit", "30"), VEHICLES, settings), Decimal("6.84"))

    def testUnknownCar(self):
        with self.assertRaisesRegex(ValueError, "unknown car golf"):
            tripCost(makeTrip("golf"), VEHICLES, DEFAULTS)


if __name__ == "__main__":
    unittest.main()
