import unittest

from metricroll.stats import percentile, summarize


class PercentileTest(unittest.TestCase):
    def test_exact_rank(self):
        self.assertEqual(percentile([3.0, 1.0, 2.0], 50), 2.0)

    def test_interpolates(self):
        self.assertAlmostEqual(percentile([10.0, 20.0, 30.0, 40.0], 50), 25.0)
        self.assertAlmostEqual(percentile(list(map(float, range(1, 101))), 95), 95.05)

    def test_bounds(self):
        self.assertEqual(percentile([5.0, 1.0], 0), 1.0)
        self.assertEqual(percentile([5.0, 1.0], 100), 5.0)

    def test_errors(self):
        with self.assertRaises(ValueError):
            percentile([], 50)
        with self.assertRaises(ValueError):
            percentile([1.0], 101)


class SummarizeTest(unittest.TestCase):
    def test_summary_fields(self):
        s = summarize([4.0, 1.0, 3.0, 2.0])
        self.assertEqual(s.n, 4)
        self.assertEqual((s.min, s.max), (1.0, 4.0))
        self.assertAlmostEqual(s.mean, 2.5)
        self.assertAlmostEqual(s.p50, 2.5)
        self.assertAlmostEqual(s.p95, 3.85)

    def test_empty(self):
        with self.assertRaises(ValueError):
            summarize([])


if __name__ == "__main__":
    unittest.main()
