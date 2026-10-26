import os
import tempfile
import unittest
from datetime import datetime

from ticketdesk.settings import DEFAULT_SETTINGS
from ticketdesk.tickets import Priority, Status, load_tickets, parse_row, parse_time

TIME_FORMAT = DEFAULT_SETTINGS["time_format"]

EXPORT = (
    "id,subject,priority,status,opened,assignee\n"
    "T-1,Printer jams,High,open,2024-05-01 09:00,dana\n"
    "T-2,VPN drops,urgent,pending,2024-05-02 14:30,\n"
)


class ParseTests(unittest.TestCase):
    def test_parse_time(self):
        value, error = parse_time(" 2024-05-01 09:15 ", TIME_FORMAT)
        self.assertIsNone(error)
        self.assertEqual(value, datetime(2024, 5, 1, 9, 15))

    def test_parse_time_bad_text(self):
        value, error = parse_time("01.05.2024", TIME_FORMAT)
        self.assertIsNone(value)
        self.assertIn("bad time", error)

    def test_parse_row(self):
        row = {"id": "T-9", "subject": " Mail ", "priority": "LOW", "status": "Closed",
               "opened": "2024-04-30 08:00", "assignee": ""}
        ticket, error = parse_row(row, TIME_FORMAT)
        self.assertIsNone(error)
        self.assertEqual(ticket.subject, "Mail")
        self.assertIs(ticket.priority, Priority.LOW)
        self.assertIs(ticket.status, Status.CLOSED)
        self.assertIsNone(ticket.assignee)

    def test_parse_row_errors(self):
        good = {"id": "T-9", "priority": "low", "status": "open", "opened": "2024-04-30 08:00"}
        cases = [
            (dict(good, id=""), "missing ticket id"),
            (dict(good, priority="soon"), "not a valid Priority"),
            (dict(good, status="done"), "not a valid Status"),
            (dict(good, opened="yesterday"), "bad time"),
        ]
        for row, message in cases:
            ticket, error = parse_row(row, TIME_FORMAT)
            self.assertIsNone(ticket)
            self.assertIn(message, error)


class LoadTicketsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "tickets.csv")

    def write(self, content):
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)

    def test_load_in_file_order(self):
        self.write(EXPORT)
        tickets, error = load_tickets(self.path, TIME_FORMAT)
        self.assertIsNone(error)
        self.assertEqual([t.ticket_id for t in tickets], ["T-1", "T-2"])
        self.assertEqual(tickets[0].assignee, "dana")

    def test_bad_row_names_the_line(self):
        self.write(EXPORT + "T-3,Phone,high,open,never,\n")
        tickets, error = load_tickets(self.path, TIME_FORMAT)
        self.assertIsNone(tickets)
        self.assertIn("tickets.csv:4: T-3: bad time", error)

    def test_duplicate_id(self):
        self.write(EXPORT + "T-1,Again,low,open,2024-05-03 10:00,\n")
        tickets, error = load_tickets(self.path, TIME_FORMAT)
        self.assertIn("duplicate ticket id T-1", error)

    def test_missing_columns_and_missing_file(self):
        self.write("id,subject\nT-1,x\n")
        tickets, error = load_tickets(self.path, TIME_FORMAT)
        self.assertIn("missing columns priority, status, opened", error)
        tickets, error = load_tickets(self.path + ".gone", TIME_FORMAT)
        self.assertIsNone(tickets)
        self.assertIn("cannot read", error)


if __name__ == "__main__":
    unittest.main()
