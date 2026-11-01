import unittest
from datetime import datetime

from ticketdesk.settings import DEFAULT_SETTINGS
from ticketdesk.sla import due_time, is_overdue, overdue_tickets, resolve_hours
from ticketdesk.tickets import Priority, Status, Ticket
from ticketdesk.worklist import active_tickets, count_by_status, sort_by_due, tickets_for

OPENED = datetime(2024, 5, 1, 9, 0)


def make_ticket(ticket_id, priority, status=Status.OPEN, assignee=None):
    return Ticket(ticket_id, "subject", priority, status, OPENED, assignee)


class SlaTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(DEFAULT_SETTINGS)

    def test_resolve_hours_per_priority(self):
        hours = [resolve_hours(p, self.settings) for p in Priority]
        self.assertEqual(hours, [168, 72, 24, 4])

    def test_due_time_uses_settings(self):
        self.settings["high_hours"] = 10
        self.assertEqual(due_time(make_ticket("T-1", Priority.HIGH), self.settings),
                         datetime(2024, 5, 1, 19, 0))

    def test_is_overdue(self):
        urgent = make_ticket("T-1", Priority.URGENT)
        self.assertFalse(is_overdue(urgent, datetime(2024, 5, 1, 13, 0), self.settings))
        self.assertTrue(is_overdue(urgent, datetime(2024, 5, 1, 13, 1), self.settings))
        closed = make_ticket("T-2", Priority.URGENT, Status.CLOSED)
        self.assertFalse(is_overdue(closed, datetime(2024, 6, 1), self.settings))

    def test_overdue_tickets_keeps_order(self):
        tickets = [make_ticket("T-1", Priority.LOW), make_ticket("T-2", Priority.URGENT),
                   make_ticket("T-3", Priority.HIGH)]
        now = datetime(2024, 5, 2, 12, 0)
        self.assertEqual([t.ticket_id for t in overdue_tickets(tickets, now, self.settings)],
                         ["T-2", "T-3"])


class WorklistTests(unittest.TestCase):
    def setUp(self):
        self.tickets = [
            make_ticket("T-3", Priority.LOW, assignee="dana"),
            make_ticket("T-1", Priority.HIGH, Status.PENDING),
            make_ticket("T-2", Priority.HIGH),
            make_ticket("T-4", Priority.URGENT, Status.CLOSED, assignee="dana"),
        ]

    def test_active_and_sorted(self):
        ordered = sort_by_due(active_tickets(self.tickets), DEFAULT_SETTINGS)
        self.assertEqual([t.ticket_id for t in ordered], ["T-1", "T-2", "T-3"])

    def test_count_by_status(self):
        self.assertEqual(count_by_status(self.tickets), {"open": 2, "pending": 1, "closed": 1})
        self.assertEqual(count_by_status([]), {"open": 0, "pending": 0, "closed": 0})

    def test_tickets_for(self):
        self.assertEqual([t.ticket_id for t in tickets_for(self.tickets, "dana")], ["T-3", "T-4"])
        self.assertEqual([t.ticket_id for t in tickets_for(self.tickets, None)], ["T-1", "T-2"])


if __name__ == "__main__":
    unittest.main()
