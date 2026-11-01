import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from fuelcost.trips import Trip, loadTrips, parseRiders
from fuelcost.vehicles import loadVehicles


class InputFilesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def writeFile(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class TestLoadVehicles(InputFilesCase):
    def testConsumptionPerCar(self):
        path = self.writeFile("vehicles.csv", "car,consumption\npolo,5.4\ntransit, 8.9 \n")
        self.assertEqual(loadVehicles(path), {"polo": Decimal("5.4"), "transit": Decimal("8.9")})

    def testInvalidRows(self):
        for text in ("car,consumption\npolo,0\n", "car,consumption\npolo,lots\n",
                     "car,consumption\npolo,5\npolo,6\n", "car\npolo\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    loadVehicles(self.writeFile("vehicles.csv", text))


class TestLoadTrips(InputFilesCase):
    def testTripsInFileOrder(self):
        path = self.writeFile("trips.csv", (
            "date,car,km,driver,riders\n"
            "2026-09-02,polo,42.5,Mia,Tom; Lea\n"
            "2026-09-01,transit,12,Tom,\n"
        ))
        self.assertEqual(loadTrips(path), [
            Trip(date(2026, 9, 2), "polo", Decimal("42.5"), "Mia", ("Tom", "Lea")),
            Trip(date(2026, 9, 1), "transit", Decimal("12"), "Tom", ()),
        ])

    def testParseRiders(self):
        self.assertEqual(parseRiders(" Tom ;;Lea"), ["Tom", "Lea"])
        self.assertEqual(parseRiders(""), [])

    def testInvalidRows(self):
        rows = ("2026-13-01,polo,10,Mia,", "2026-09-01,polo,far,Mia,", "2026-09-01,polo,0,Mia,",
                "2026-09-01,polo,10,,Tom", "2026-09-01,polo,10,Mia,Tom;Mia",
                "2026-09-01,polo,10,Mia,Tom;Tom")
        for row in rows:
            with self.subTest(row=row):
                path = self.writeFile("trips.csv", "date,car,km,driver,riders\n" + row + "\n")
                with self.assertRaises(ValueError):
                    loadTrips(path)


if __name__ == "__main__":
    unittest.main()
