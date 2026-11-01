import unittest
from datetime import datetime

from logsift.parser import level_rank, normalize_level, parse_fields, parse_line


class ParseLineTest(unittest.TestCase):
    def test_full_line(self):
        entry = parse_line(
            "2024-05-01T12:00:03 ERROR [api] request failed path=/orders status=500 duration_ms=812"
        )
        self.assertEqual(entry.timestamp, datetime(2024, 5, 1, 12, 0, 3))
        self.assertEqual(entry.level, "ERROR")
        self.assertEqual(entry.source, "api")
        self.assertEqual(
            entry.fields, {"path": "/orders", "status": "500", "duration_ms": "812"}
        )

    def test_space_separated_timestamp_and_alias_level(self):
        entry = parse_line("2024-05-01 08:15:00 WARN [worker-2] queue is getting long")
        self.assertEqual(entry.level, "WARNING")
        self.assertEqual(entry.source, "worker-2")
        self.assertEqual(entry.fields, {})

    def test_rejects_other_lines(self):
        self.assertIsNone(parse_line("Traceback (most recent call last):"))
        self.assertIsNone(parse_line("2024-05-01T12:00:03 LOUD [api] unknown level"))
        self.assertIsNone(parse_line("2024-13-01T12:00:03 INFO [api] bad month"))


class LevelTest(unittest.TestCase):
    def test_normalize_level(self):
        self.assertEqual(normalize_level(" fatal "), "CRITICAL")
        self.assertIsNone(normalize_level("verbose"))

    def test_level_rank(self):
        self.assertLess(level_rank("info"), level_rank("warn"))
        with self.assertRaises(ValueError):
            level_rank("verbose")


class ParseFieldsTest(unittest.TestCase):
    def test_later_keys_win(self):
        self.assertEqual(parse_fields("retry n=1 n=2 user=bob"), {"n": "2", "user": "bob"})
