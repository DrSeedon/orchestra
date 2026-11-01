import unittest

from metricroll.series import Sample, load_series, parse_line, values_of


class ParseLineTest(unittest.TestCase):
    def test_parses_three_fields(self):
        self.assertEqual(parse_line("cpu 1700000000 42.5"), ("cpu", Sample(1700000000, 42.5)))

    def test_rejects_wrong_field_count(self):
        with self.assertRaises(ValueError):
            parse_line("cpu 1700000000")

    def test_rejects_bad_number(self):
        with self.assertRaises(ValueError):
            parse_line("cpu now 42.5")

    def test_rejects_negative_timestamp(self):
        with self.assertRaises(ValueError):
            parse_line("cpu -5 1")


class LoadSeriesTest(unittest.TestCase):
    def test_groups_and_sorts(self):
        lines = [
            "# comment",
            "cpu 20 2.0",
            "mem 10 512",
            "",
            "cpu 10 1.0",
        ]
        series = load_series(lines)
        self.assertEqual(sorted(series), ["cpu", "mem"])
        self.assertEqual(series["cpu"], [Sample(10, 1.0), Sample(20, 2.0)])
        self.assertEqual(values_of(series["cpu"]), [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
