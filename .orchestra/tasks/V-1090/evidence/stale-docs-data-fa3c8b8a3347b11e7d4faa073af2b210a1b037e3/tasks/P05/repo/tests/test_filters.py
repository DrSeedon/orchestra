import unittest
from datetime import datetime

from logsift.filters import at_least, between, containing, from_sources
from logsift.parser import parse_line

LINES = [
    "2024-05-01T10:00:00 DEBUG [api] cache warm",
    "2024-05-01T10:05:00 INFO [api] request done duration_ms=30",
    "2024-05-01T10:10:00 WARNING [worker] Retrying job 7",
    "2024-05-01T11:00:00 ERROR [db] connection reset",
]


class FiltersTest(unittest.TestCase):
    def setUp(self):
        self.entries = [parse_line(line) for line in LINES]

    def test_at_least(self):
        kept = at_least(self.entries, "warn")
        self.assertEqual([entry.level for entry in kept], ["WARNING", "ERROR"])

    def test_at_least_unknown_level(self):
        with self.assertRaises(ValueError):
            at_least(self.entries, "loud")

    def test_from_sources(self):
        kept = from_sources(self.entries, [" api", "db"])
        self.assertEqual(len(kept), 3)

    def test_between_is_half_open(self):
        kept = between(self.entries, datetime(2024, 5, 1, 10, 5), datetime(2024, 5, 1, 11, 0))
        self.assertEqual([entry.source for entry in kept], ["api", "worker"])

    def test_between_rejects_empty_window(self):
        moment = datetime(2024, 5, 1, 10, 0)
        with self.assertRaises(ValueError):
            between(self.entries, moment, moment)

    def test_containing_ignores_case(self):
        self.assertEqual(len(containing(self.entries, "retrying")), 1)
