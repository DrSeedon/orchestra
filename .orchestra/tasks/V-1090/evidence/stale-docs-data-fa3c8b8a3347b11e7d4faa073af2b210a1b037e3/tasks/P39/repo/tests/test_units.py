import unittest

from sizechart.units import Unit, parse_unit, to_cm


class UnitsTest(unittest.TestCase):
    def test_parse_unit(self):
        self.assertIs(parse_unit("cm"), Unit.CM)
        self.assertIs(parse_unit(" IN "), Unit.INCH)

    def test_unknown_unit(self):
        with self.assertRaisesRegex(ValueError, "unknown unit"):
            parse_unit("ft")

    def test_to_cm(self):
        self.assertEqual(to_cm(90.0, Unit.CM), 90.0)
        self.assertAlmostEqual(to_cm(10.0, Unit.INCH), 25.4)


if __name__ == "__main__":
    unittest.main()
