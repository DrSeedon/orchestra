"""Service level targets: when a ticket is due and whether it is overdue."""

from datetime import datetime, timedelta

from ticketdesk.tickets import Priority, Status, Ticket


def resolve_hours(priority: Priority, settings: dict[str, object]) -> int:
    """Hours allowed to resolve a ticket of the given priority."""
    if priority is Priority.URGENT:
        return settings["urgent_hours"]
    if priority is Priority.HIGH:
        return settings["high_hours"]
    if priority is Priority.NORMAL:
        return settings["normal_hours"]
    return settings["low_hours"]


def due_time(ticket: Ticket, settings: dict[str, object]) -> datetime:
    """The time by which the ticket must be resolved."""
    return ticket.opened + timedelta(hours=resolve_hours(ticket.priority, settings))


def is_overdue(ticket: Ticket, now: datetime, settings: dict[str, object]) -> bool:
    """True when the ticket is not closed and its due time has passed."""
    return ticket.status is not Status.CLOSED and due_time(ticket, settings) < now


def overdue_tickets(tickets: list[Ticket], now: datetime, settings: dict[str, object]) -> list[Ticket]:
    """The overdue tickets, in the order given."""
    return [ticket for ticket in tickets if is_overdue(ticket, now, settings)]
