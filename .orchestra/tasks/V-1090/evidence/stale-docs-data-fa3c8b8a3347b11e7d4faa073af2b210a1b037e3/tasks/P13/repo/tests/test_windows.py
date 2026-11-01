import unittest

from metricroll.series import Sample
from metricroll.windows import bucket, rollup, rollup_all, window_start

SAMPLES = [Sample(0, 1.0), Sample(30, 3.0), Sample(60, 10.0), Sample(170, 20.0)]


class WindowTest(unittest.TestCase):
    def test_window_start(self):
        self.assertEqual(window_start(125, 60), 120)
        with self.assertRaises(ValueError):
            window_start(10, 0)

    def test_bucket(self):
        buckets = bucket(SAMPLES, 60)
        self.assertEqual(sorted(buckets), [0, 60, 120])
        self.assertEqual(len(buckets[0]), 2)

    def test_rollup_skips_empty_windows(self):
        rolled = rollup(SAMPLES, 60)
        self.assertEqual([start for start, _ in rolled], [0, 60, 120])
        self.assertEqual(rolled[0][1].mean, 2.0)

    def test_rollup_all(self):
        rolled = rollup_all({"b": SAMPLES[:1], "a": SAMPLES}, 100)
        self.assertEqual(list(rolled), ["a", "b"])
        self.assertEqual(len(rolled["a"]), 2)


if __name__ == "__main__":
    unittest.main()
