import os
import tempfile
import unittest

from sizechart.chart import Measure, SizeRange, find_size, load_chart

HEADER = "size,chest_min,chest_max,waist_min,waist_max,hip_min,hip_max\n"


class ChartTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def write_chart(self, text):
        path = os.path.join(self.folder.name, "chart.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_load_chart(self):
        path = self.write_chart(HEADER + "S,86,94,71,79,88,96\nM,94,102,79,87,96,104\n")
        chart = load_chart(path)
        self.assertEqual([size.label for size in chart], ["S", "M"])
        self.assertEqual(chart[1].ranges[Measure.WAIST], SizeRange(79.0, 87.0))

    def test_range_contains_both_ends(self):
        size_range = SizeRange(79.0, 87.0)
        self.assertTrue(size_range.contains(79.0))
        self.assertTrue(size_range.contains(87.0))
        self.assertFalse(size_range.contains(87.5))

    def test_missing_column(self):
        path = self.write_chart("size,chest_min,chest_max\nS,86,94\n")
        with self.assertRaisesRegex(ValueError, "missing column waist_min"):
            load_chart(path)

    def test_bad_value(self):
        path = self.write_chart(HEADER + "S,86,94,71,79,88,96\nM,94,big,79,87,96,104\n")
        with self.assertRaisesRegex(ValueError, "line 3: bad chest value"):
            load_chart(path)

    def test_minimum_above_maximum(self):
        path = self.write_chart(HEADER + "S,86,94,79,71,88,96\n")
        with self.assertRaisesRegex(ValueError, "waist minimum"):
            load_chart(path)

    def test_label_twice(self):
        path = self.write_chart(HEADER + "S,86,94,71,79,88,96\ns,86,94,71,79,88,96\n")
        with self.assertRaisesRegex(ValueError, "appears twice"):
            load_chart(path)

    def test_find_size(self):
        chart = load_chart(self.write_chart(HEADER + "S,86,94,71,79,88,96\nXL,110,118,95,103,112,120\n"))
        self.assertEqual(find_size(chart, "xl").label, "XL")
        with self.assertRaises(KeyError):
            find_size(chart, "XXL")


if __name__ == "__main__":
    unittest.main()
