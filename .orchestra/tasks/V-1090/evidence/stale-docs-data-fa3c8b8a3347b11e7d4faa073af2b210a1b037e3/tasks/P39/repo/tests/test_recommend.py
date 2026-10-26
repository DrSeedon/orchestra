import unittest

from sizechart.chart import Measure, Size, SizeRange
from sizechart.people import Person
from sizechart.recommend import fits, recommend


def make_size(label, chest, waist, hip):
    return Size(label, {Measure.CHEST: SizeRange(*chest), Measure.WAIST: SizeRange(*waist),
                        Measure.HIP: SizeRange(*hip)})


CHART = [
    make_size("S", (86, 94), (71, 79), (88, 96)),
    make_size("M", (94, 102), (79, 87), (96, 104)),
]


def make_person(chest, waist, hip):
    return Person("Ana", {Measure.CHEST: chest, Measure.WAIST: waist, Measure.HIP: hip})


class RecommendTest(unittest.TestCase):
    def test_fits(self):
        self.assertTrue(fits(CHART[1], make_person(98, 83, 100)))
        self.assertFalse(fits(CHART[0], make_person(98, 83, 100)))

    def test_smallest_fitting_size(self):
        self.assertEqual(recommend(CHART, make_person(94, 79, 96)).label, "S")
        self.assertEqual(recommend(CHART, make_person(95, 79, 96)).label, "M")

    def test_no_size(self):
        self.assertIsNone(recommend(CHART, make_person(120, 83, 100)))


if __name__ == "__main__":
    unittest.main()
