"""Work lists for the desk: active tickets, ordering and counts."""

from ticketdesk.sla import due_time
from ticketdesk.tickets import Status, Ticket


def active_tickets(tickets: list[Ticket]) -> list[Ticket]:
    """Tickets that are open or pending."""
    return [ticket for ticket in tickets if ticket.status is not Status.CLOSED]


def sort_by_due(tickets: list[Ticket], settings: dict[str, object]) -> list[Ticket]:
    """Tickets ordered by due time, then by id."""
    return sorted(tickets, key=lambda ticket: (due_time(ticket, settings), ticket.ticket_id))


def count_by_status(tickets: list[Ticket]) -> dict[str, int]:
    """Number of tickets per status name; every status is present."""
    counts = {status.value: 0 for status in Status}
    for ticket in tickets:
        counts[ticket.status.value] += 1
    return counts


def tickets_for(tickets: list[Ticket], assignee: str | None) -> list[Ticket]:
    """Tickets of one assignee; None selects the unassigned tickets."""
    return [ticket for ticket in tickets if ticket.assignee == assignee]
