"""Lay out the day of one room as busy and free slots."""
from roomsched.clock import format_time

SLOT_BUSY = "busy"
SLOT_FREE = "free"


def ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    """Tell whether two time ranges share at least one minute.

    Ranges that only touch, where one ends when the other starts, do not overlap.

    :param start_a: start of the first range, in minutes after midnight.
    :param end_a: end of the first range.
    :param start_b: start of the second range.
    :param end_b: end of the second range.
    :returns: True when the ranges overlap.
    """
    return start_a < end_b and start_b < end_a


def make_slot(start: int, end: int, kind: str, booking_id: str = "") -> dict:
    """Build one agenda slot.

    :param start: start in minutes after midnight.
    :param end: end in minutes after midnight.
    :param kind: ``SLOT_BUSY`` or ``SLOT_FREE``.
    :param booking_id: the booking that fills a busy slot.
    :returns: a slot with the keys ``start``, ``end`` (as ``HH:MM``), ``slot`` and ``booking``.
    """
    return {"start": format_time(start), "end": format_time(end), "slot": kind, "booking": booking_id}


def day_slots(room: dict, bookings: list[dict]) -> tuple[list[dict] | None, str | None]:
    """Split the opening hours of a room into busy and free slots.

    Busy slots keep the real booking times, even outside opening hours. Free slots
    only cover the opening hours.

    :param room: the room, as loaded from the rooms file.
    :param bookings: the active bookings of this room on one day, sorted by start.
    :returns: ``(slots, None)`` in time order, or ``(None, message)`` when two
        bookings overlap.
    """
    slots = []
    cursor = room["opens"]
    last = None
    for booking in bookings:
        if last is not None and ranges_overlap(
            last["start"], last["end"], booking["start"], booking["end"]
        ):
            return None, f"{room['name']}: booking {booking['id']} overlaps {last['id']}"
        if booking["start"] > cursor and cursor < room["closes"]:
            slots.append(make_slot(cursor, min(booking["start"], room["closes"]), SLOT_FREE))
        slots.append(make_slot(booking["start"], booking["end"], SLOT_BUSY, booking["id"]))
        cursor = max(cursor, booking["end"])
        last = booking
    if cursor < room["closes"]:
        slots.append(make_slot(cursor, room["closes"], SLOT_FREE))
    return slots, None
