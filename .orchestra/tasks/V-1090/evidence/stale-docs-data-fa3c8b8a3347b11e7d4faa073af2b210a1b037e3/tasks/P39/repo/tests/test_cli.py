import contextlib
import io
import os
import tempfile
import unittest

from sizechart.cli import main

CHART = ("size,chest_min,chest_max,waist_min,waist_max,hip_min,hip_max\n"
         "S,86,94,71,79,88,96\nM,94,102,79,87,96,104\n")
PEOPLE = "name,chest,waist,hip,unit\nAna,98,83,100,cm\nBo,90,75,92,cm\nCy,130,83,100,cm\n"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.chart = self.write("chart.csv", CHART)
        self.people = self.write("people.csv", PEOPLE)

    def write(self, name, text):
        path = os.path.join(self.folder.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_sizes_per_person(self):
        status, out, _ = self.run_main(self.chart, self.people)
        self.assertEqual(status, 0)
        self.assertEqual(out.splitlines(), ["Ana: M", "Bo: S", "Cy: no size"])

    def test_missing_file(self):
        status, out, err = self.run_main(self.chart, os.path.join(self.folder.name, "none.csv"))
        self.assertEqual(status, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
