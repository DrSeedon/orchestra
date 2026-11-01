"""Tickets read from the helpdesk CSV export.

The export has the columns id, subject, priority, status, opened and assignee.
Times use the time format from the settings.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

REQUIRED_COLUMNS = ("id", "priority", "status", "opened")


class Priority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Status(Enum):
    OPEN = "open"
    PENDING = "pending"
    CLOSED = "closed"


@dataclass
class Ticket:
    ticket_id: str
    subject: str
    priority: Priority
    status: Status
    opened: datetime
    assignee: str | None = None


def parse_time(text: str, time_format: str) -> tuple[datetime | None, str | None]:
    """Return (time, None), or (None, message) when text does not match time_format."""
    try:
        value = datetime.strptime(text.strip(), time_format)
    except ValueError:
        return None, f"bad time {text!r}, expected the format {time_format}"
    return value, None


def parse_row(row: dict[str, str | None], time_format: str) -> tuple[Ticket | None, str | None]:
    """Return (ticket, None) for one export row, or (None, message)."""
    text = {key: (value or "").strip() for key, value in row.items() if key is not None}
    ticket_id = text.get("id", "")
    if not ticket_id:
        return None, "missing ticket id"
    try:
        priority = Priority(text.get("priority", "").lower())
        status = Status(text.get("status", "").lower())
    except ValueError as err:
        return None, f"{ticket_id}: {err}"
    opened, error = parse_time(text.get("opened", ""), time_format)
    if error is not None:
        return None, f"{ticket_id}: {error}"
    ticket = Ticket(ticket_id, text.get("subject", ""), priority, status, opened,
                    text.get("assignee") or None)
    return ticket, None


def load_tickets(path: str, time_format: str) -> tuple[list[Ticket] | None, str | None]:
    """Return (tickets, None) in file order, or (None, message) for the first bad row."""
    tickets: list[Ticket] = []
    seen: set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
            if missing:
                return None, f"{path}: missing columns {', '.join(missing)}"
            for line_no, row in enumerate(reader, start=2):
                ticket, error = parse_row(row, time_format)
                if error is not None:
                    return None, f"{path}:{line_no}: {error}"
                if ticket.ticket_id in seen:
                    return None, f"{path}:{line_no}: duplicate ticket id {ticket.ticket_id}"
                seen.add(ticket.ticket_id)
                tickets.append(ticket)
    except OSError as err:
        return None, f"cannot read {path}: {err.strerror}"
    return tickets, None
