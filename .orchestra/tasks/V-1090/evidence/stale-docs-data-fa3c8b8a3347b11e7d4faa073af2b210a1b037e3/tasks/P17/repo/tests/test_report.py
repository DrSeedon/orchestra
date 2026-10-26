import json
import os
import tempfile
import unittest

from ticketdesk.report import main

EXPORT = (
    "id,subject,priority,status,opened,assignee\n"
    "T-1,Printer jams,high,open,2024-05-01 09:00,dana\n"
    "T-2,VPN drops,urgent,pending,2024-05-02 14:30,\n"
    "T-3,New laptop,low,closed,2024-04-20 10:00,lee\n"
    "T-4,Mailbox full,normal,open,2024-05-01 08:00,\n"
)


class ReportCommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name
        self.tickets = self.write("tickets.csv", EXPORT)
        self.output = os.path.join(self.folder, "report.csv")

    def write(self, name, content):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return path

    def read_output(self):
        with open(self.output, encoding="utf-8", newline="") as fh:
            return [line.rstrip("\r\n") for line in fh]

    def test_report_rows(self):
        self.assertEqual(main([self.tickets, "2024-05-02 20:00", self.output]), 0)
        self.assertEqual(self.read_output(), [
            "id,priority,status,due,overdue",
            "T-1,high,open,2024-05-02 09:00,yes",
            "T-2,urgent,pending,2024-05-02 18:30,yes",
            "T-4,normal,open,2024-05-04 08:00,no",
        ])

    def test_settings_file_changes_hours(self):
        settings = self.write("settings.json", json.dumps({"normal_hours": 24}))
        self.assertEqual(main([self.tickets, "2024-05-02 20:00", self.output, "--settings", settings]), 0)
        self.assertIn("T-4,normal,open,2024-05-02 08:00,yes", self.read_output())

    def test_bad_input_exits_2(self):
        self.assertEqual(main([self.tickets, "tomorrow", self.output]), 2)
        settings = self.write("settings.json", json.dumps({"low_hours": -1}))
        self.assertEqual(main([self.tickets, "2024-05-02 20:00", self.output, "--settings", settings]), 2)
        self.assertEqual(main([self.tickets + ".gone", "2024-05-02 20:00", self.output]), 2)
        self.assertFalse(os.path.exists(self.output))


if __name__ == "__main__":
    unittest.main()
