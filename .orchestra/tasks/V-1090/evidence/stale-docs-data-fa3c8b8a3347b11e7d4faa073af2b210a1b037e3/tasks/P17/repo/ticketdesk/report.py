"""SLA report for the active tickets.

Usage: python -m ticketdesk.report TICKETS NOW OUTPUT [--settings FILE]

Writes one CSV row per open or pending ticket, ordered by due time.
"""

import argparse
import csv
import sys
from datetime import datetime

from ticketdesk.settings import load_settings
from ticketdesk.sla import due_time, is_overdue
from ticketdesk.tickets import Ticket, load_tickets, parse_time
from ticketdesk.worklist import active_tickets, count_by_status, sort_by_due

REPORT_HEADER = ("id", "priority", "status", "due", "overdue")


def report_rows(tickets: list[Ticket], now: datetime, settings: dict[str, object]) -> list[list[str]]:
    """One row per active ticket: id, priority, status, due time, overdue yes/no."""
    rows = []
    for ticket in sort_by_due(active_tickets(tickets), settings):
        due = due_time(ticket, settings).strftime(settings["time_format"])
        overdue = "yes" if is_overdue(ticket, now, settings) else "no"
        rows.append([ticket.ticket_id, ticket.priority.value, ticket.status.value, due, overdue])
    return rows


def write_report(path: str, rows: list[list[str]]) -> None:
    """Write the rows as CSV with a header line."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(REPORT_HEADER)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ticketdesk.report",
                                     description="Write the SLA report for the active tickets.")
    parser.add_argument("tickets", help="CSV export of the tickets")
    parser.add_argument("now", help="current time, in the time format of the settings")
    parser.add_argument("output", help="CSV file to write")
    parser.add_argument("--settings", help="JSON settings file")
    args = parser.parse_args(argv)

    settings, error = load_settings(args.settings)
    if error is None:
        now, error = parse_time(args.now, settings["time_format"])
    if error is None:
        tickets, error = load_tickets(args.tickets, settings["time_format"])
    if error is not None:
        print(f"error: {error}", file=sys.stderr)
        return 2
    rows = report_rows(tickets, now, settings)
    write_report(args.output, rows)
    counts = count_by_status(tickets)
    overdue = sum(1 for row in rows if row[-1] == "yes")
    print(f"{len(rows)} active tickets ({counts['open']} open, {counts['pending']} pending), "
          f"{overdue} overdue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
