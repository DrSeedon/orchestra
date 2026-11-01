import contextlib
import io
import os
import tempfile
import unittest

from fuelcost.__main__ import main

TRIPS = (
    "date,car,km,driver,riders\n"
    "2026-09-01,polo,100,Mia,Tom;Lea\n"
    "2026-09-03,transit,30,Tom,\n"
)
VEHICLES = "car,consumption\npolo,5.4\ntransit,8.9\n"


class TestReportCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.trips = self.writeFile("trips.csv", TRIPS)
        self.vehicles = self.writeFile("vehicles.csv", VEHICLES)
        self.output = os.path.join(self.tmp.name, "report.csv")

    def writeFile(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def runMain(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            status = main([self.trips, self.vehicles, self.output, *extra])
        return status, out.getvalue()

    def testWritesReport(self):
        status, out = self.runMain()
        self.assertEqual(status, 0)
        with open(self.output, encoding="utf-8") as handle:
            self.assertEqual(handle.read().splitlines(), [
                "date,car,km,litres,cost",
                "2026-09-01,polo,100,5.40,9.99",
                "2026-09-03,transit,30,2.67,4.94",
                "total,,130,8.07,14.93",
            ])
        self.assertIn("total 14.93 EUR", out)

    def testSettingsFile(self):
        settings = self.writeFile("settings.json", '{"price": "2.00", "currency": "CHF"}')
        status, out = self.runMain("--settings", settings)
        self.assertEqual(status, 0)
        self.assertIn("total 16.14 CHF", out)

    def testUnknownCar(self):
        self.writeFile("vehicles.csv", "car,consumption\npolo,5.4\n")
        status, _ = self.runMain()
        self.assertEqual(status, 2)
        self.assertFalse(os.path.exists(self.output))


if __name__ == "__main__":
    unittest.main()
