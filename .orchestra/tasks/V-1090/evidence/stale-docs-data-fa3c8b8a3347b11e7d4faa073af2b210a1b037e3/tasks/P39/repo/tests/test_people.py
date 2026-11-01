import os
import tempfile
import unittest

from sizechart.chart import Measure
from sizechart.people import load_people

HEADER = "name,chest,waist,hip,unit\n"


class PeopleTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def write_people(self, text):
        path = os.path.join(self.folder.name, "people.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_load_people_in_cm(self):
        people = load_people(self.write_people(HEADER + "Ana,98,83,100,cm\nBen,40,32,39,in\n"))
        self.assertEqual([person.name for person in people], ["Ana", "Ben"])
        self.assertEqual(people[0].measurements[Measure.HIP], 100.0)
        self.assertAlmostEqual(people[1].measurements[Measure.CHEST], 101.6)

    def test_unknown_unit(self):
        path = self.write_people(HEADER + "Ana,98,83,100,ft\n")
        with self.assertRaisesRegex(ValueError, "line 2: unknown unit"):
            load_people(path)

    def test_measurement_above_zero(self):
        path = self.write_people(HEADER + "Ana,98,0,100,cm\n")
        with self.assertRaisesRegex(ValueError, "waist must be above zero"):
            load_people(path)

    def test_empty_name(self):
        path = self.write_people(HEADER + " ,98,83,100,cm\n")
        with self.assertRaisesRegex(ValueError, "name is empty"):
            load_people(path)


if __name__ == "__main__":
    unittest.main()
