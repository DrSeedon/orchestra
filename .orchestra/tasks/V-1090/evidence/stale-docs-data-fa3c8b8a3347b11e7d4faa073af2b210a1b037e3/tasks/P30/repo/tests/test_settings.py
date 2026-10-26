import os
import tempfile
import unittest
from decimal import Decimal

from fuelcost.settings import DEFAULTS, loadSettings


class TestLoadSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def writeSettings(self, text):
        path = os.path.join(self.tmp.name, "settings.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def testDefaultsWithoutFile(self):
        self.assertEqual(loadSettings(None), DEFAULTS)

    def testFileUpdatesDefaults(self):
        settings = loadSettings(self.writeSettings('{"price": 1.799, "currency": "chf"}'))
        self.assertEqual(settings["price"], Decimal("1.799"))
        self.assertEqual(settings["currency"], "CHF")
        self.assertEqual(settings["wear"], Decimal("0.00"))

    def testPriceAsText(self):
        settings = loadSettings(self.writeSettings('{"price": "2.05", "wear": "0.04"}'))
        self.assertEqual(settings["price"], Decimal("2.05"))
        self.assertEqual(settings["wear"], Decimal("0.04"))

    def testInvalidValues(self):
        for text in ('{"price": 0}', '{"price": "cheap"}', '{"wear": -1}', '{"currency": ""}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    loadSettings(self.writeSettings(text))

    def testUnknownSetting(self):
        with self.assertRaisesRegex(ValueError, "unknown setting 'speed'"):
            loadSettings(self.writeSettings('{"speed": 120}'))

    def testNotJson(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            loadSettings(self.writeSettings("price = 1.80"))

    def testMissingFile(self):
        with self.assertRaises(OSError):
            loadSettings(os.path.join(self.tmp.name, "nope.json"))


if __name__ == "__main__":
    unittest.main()
