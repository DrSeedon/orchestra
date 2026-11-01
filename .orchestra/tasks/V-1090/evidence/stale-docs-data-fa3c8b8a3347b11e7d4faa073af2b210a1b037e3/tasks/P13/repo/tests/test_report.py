import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from metricroll.report import format_summary, main, render_report
from metricroll.series import Sample
from metricroll.windows import rollup, rollup_all

SAMPLES = [Sample(0, 1.0), Sample(30, 3.0), Sample(60, 10.0), Sample(170, 20.0)]


class ReportTest(unittest.TestCase):
    def test_format_summary(self):
        start, summary = rollup(SAMPLES, 60)[0]
        line = format_summary("cpu", start, summary)
        self.assertTrue(line.startswith("cpu"))
        self.assertIn("min=1.00 max=3.00", line)

    def test_render_report_headers(self):
        lines = render_report(rollup_all({"cpu": SAMPLES}, 60))
        self.assertEqual(lines[0], "== cpu (3 windows) ==")
        self.assertEqual(len(lines), 4)


class MainTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.samples = os.path.join(self.folder, "samples.txt")
        self.output = os.path.join(self.folder, "report.txt")

    def write_samples(self, text):
        with open(self.samples, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main([self.samples, self.output, *args])

    def test_writes_report(self):
        self.write_samples("cpu 0 1.0\ncpu 30 3.0\nmem 400 512\n")
        self.assertEqual(self.run_main("--width", "300"), 0)
        with open(self.output, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines[0], "== cpu (1 windows) ==")
        self.assertEqual(lines[2], "== mem (1 windows) ==")
        self.assertIn("300", lines[3])

    def test_bad_samples_file(self):
        self.write_samples("cpu zero 1.0\n")
        self.assertEqual(self.run_main(), 2)
        self.assertFalse(os.path.exists(self.output))

    def test_missing_samples_file(self):
        self.assertEqual(self.run_main(), 2)


if __name__ == "__main__":
    unittest.main()
