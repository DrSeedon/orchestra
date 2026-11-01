import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime

from logsift.parser import parse_line
from logsift.report import main, print_summary, render_summary
from logsift.summary import (
    count_by_level,
    count_by_source,
    error_rate,
    message_shape,
    time_span,
    top_messages,
)

LINES = [
    "2024-05-01T10:00:00 INFO [api] request 17 done duration_ms=30",
    "2024-05-01T10:01:00 INFO [api] request 18 done duration_ms=45",
    "2024-05-01T10:02:00 ERROR [db] connection reset",
    "2024-05-01T10:03:00 CRITICAL [db] pool exhausted",
]


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.entries = [parse_line(line) for line in LINES]

    def test_count_by_level_includes_zeros(self):
        self.assertEqual(
            count_by_level(self.entries),
            {"DEBUG": 0, "INFO": 2, "WARNING": 0, "ERROR": 1, "CRITICAL": 1},
        )

    def test_count_by_source(self):
        self.assertEqual(count_by_source(self.entries), {"api": 2, "db": 2})

    def test_message_shape_groups_similar_messages(self):
        self.assertEqual(message_shape("request 17 done duration_ms=30"), "request # done")
        self.assertEqual(top_messages(self.entries, 1), [("request # done", 2)])

    def test_top_messages_needs_positive_limit(self):
        with self.assertRaises(ValueError):
            top_messages(self.entries, 0)

    def test_error_rate_and_span(self):
        self.assertAlmostEqual(error_rate(self.entries), 0.5)
        self.assertEqual(error_rate([]), 0.0)
        self.assertEqual(
            time_span(self.entries),
            (datetime(2024, 5, 1, 10, 0), datetime(2024, 5, 1, 10, 3)),
        )
        self.assertIsNone(time_span([]))


class ReportTest(unittest.TestCase):
    def test_render_summary(self):
        lines = render_summary([parse_line(line) for line in LINES], top=2)
        self.assertEqual(lines[0], "4 entries from 2024-05-01T10:00:00 to 2024-05-01T10:03:00")
        self.assertEqual(lines[2], "error rate: 50.0%")
        self.assertEqual(lines[3], "sources: api (2), db (2)")

    def test_print_summary_of_nothing(self):
        out = io.StringIO()
        with redirect_stdout(out):
            print_summary([])
        self.assertEqual(out.getvalue(), "no entries\n")


class ReportCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_prints_summary(self):
        path = os.path.join(self.tmp.name, "app.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(LINES) + "\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main([path, "--top", "1"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "4 entries from 2024-05-01T10:00:00 to 2024-05-01T10:03:00")
        self.assertEqual(lines[3], "sources: api (2)")

    def test_missing_file(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main([os.path.join(self.tmp.name, "none.log")]), 2)
