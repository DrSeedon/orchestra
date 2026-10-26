import json
import os
import tempfile
import unittest

from ticketdesk.settings import DEFAULT_SETTINGS, load_settings


class LoadSettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name

    def write(self, content):
        path = os.path.join(self.folder, "settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_defaults_without_file(self):
        settings, error = load_settings()
        self.assertIsNone(error)
        self.assertEqual(settings, DEFAULT_SETTINGS)
        self.assertIsNot(settings, DEFAULT_SETTINGS)

    def test_file_overrides_some_keys(self):
        settings, error = load_settings(self.write(json.dumps({"high_hours": 8})))
        self.assertIsNone(error)
        self.assertEqual(settings["high_hours"], 8)
        self.assertEqual(settings["low_hours"], 168)

    def test_unknown_key(self):
        settings, error = load_settings(self.write(json.dumps({"colour": "red"})))
        self.assertIsNone(settings)
        self.assertIn("unknown setting 'colour'", error)

    def test_wrong_type(self):
        for value in ("8", 8.5, True):
            settings, error = load_settings(self.write(json.dumps({"high_hours": value})))
            self.assertIsNone(settings)
            self.assertIn("must be of type int", error)

    def test_hours_must_be_positive(self):
        settings, error = load_settings(self.write(json.dumps({"urgent_hours": 0})))
        self.assertIsNone(settings)
        self.assertIn("greater than 0", error)

    def test_unreadable_or_invalid_file(self):
        settings, error = load_settings(os.path.join(self.folder, "missing.json"))
        self.assertIsNone(settings)
        self.assertIn("cannot read settings file", error)
        settings, error = load_settings(self.write("{not json"))
        self.assertIsNone(settings)
        self.assertIn("not valid JSON", error)
        settings, error = load_settings(self.write("[1, 2]"))
        self.assertIn("expected a JSON object", error)


if __name__ == "__main__":
    unittest.main()
