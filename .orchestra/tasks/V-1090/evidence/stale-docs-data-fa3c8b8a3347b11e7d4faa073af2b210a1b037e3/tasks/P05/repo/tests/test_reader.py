import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr

from logsift.reader import parse_lines, read_log_files

FIRST = (
    "2024-05-01T12:00:05 INFO [api] request done duration_ms=40\n"
    "not a log line\n"
    "\n"
    "2024-05-01T12:00:01 ERROR [db] connection reset\n"
)
SECOND = "2024-05-01T12:00:03 WARNING [worker] slow job duration_ms=2500\n"


class ParseLinesTest(unittest.TestCase):
    def test_skips_and_reports_bad_lines(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            entries = parse_lines(FIRST.splitlines(keepends=True), "app.log")
        self.assertEqual([entry.source for entry in entries], ["api", "db"])
        self.assertIn("warning: app.log:2: unparsable line skipped", stderr.getvalue())
        self.assertIn("app.log: 1 line(s) skipped, 2 parsed", stderr.getvalue())


class ReadLogFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_merges_in_timestamp_order(self):
        paths = [self.write("a.log", FIRST), self.write("b.log", SECOND)]
        with redirect_stderr(io.StringIO()):
            entries = read_log_files(paths)
        self.assertEqual([entry.source for entry in entries], ["db", "worker", "api"])
