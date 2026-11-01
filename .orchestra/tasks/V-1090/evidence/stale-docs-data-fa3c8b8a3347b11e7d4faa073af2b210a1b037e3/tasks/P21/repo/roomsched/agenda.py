"""Write the agenda of every room for one day.

Run as ``python -m roomsched.agenda ROOMS_CSV BOOKINGS_CSV DAY OUTPUT_CSV``.
"""
import csv
import sys

from roomsched.bookings import active_bookings, bookings_for, load_bookings
from roomsched.clock import parse_day
from roomsched.rooms import load_rooms
from roomsched.schedule import day_slots

AGENDA_COLUMNS = ("room", "start", "end", "slot", "booking")
USAGE = "usage: python -m roomsched.agenda ROOMS_CSV BOOKINGS_CSV DAY OUTPUT_CSV"


def build_agenda(
    rooms: dict[str, dict], bookings: list[dict], day: str
) -> tuple[list[dict] | None, str | None]:
    """Build the agenda rows of all rooms for one day.

    :param rooms: the rooms keyed by name.
    :param bookings: all bookings; cancelled ones and other days are left out.
    :param day: the day in ISO form.
    :returns: ``(rows, None)`` with the rows sorted by room name and time, or
        ``(None, message)`` when a booking names an unknown room or two bookings overlap.
    """
    for booking in bookings:
        if booking["room"] not in rooms:
            return None, f"booking {booking['id']}: unknown room {booking['room']!r}"
    active = active_bookings(bookings)
    rows = []
    for name in sorted(rooms):
        slots, error = day_slots(rooms[name], bookings_for(active, name, day))
        if error:
            return None, error
        rows.extend(dict(slot, room=name) for slot in slots)
    return rows, None


def write_agenda(rows: list[dict], path: str) -> None:
    """Write agenda rows to a CSV file.

    :param rows: rows as returned by ``build_agenda``.
    :param path: the CSV file to write.
    """
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AGENDA_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str]) -> int:
    """Run the agenda command.

    :param argv: the arguments ``ROOMS_CSV BOOKINGS_CSV DAY OUTPUT_CSV``.
    :returns: the exit status: 0 on success, 2 when the input is invalid.
    """
    if len(argv) != 4:
        print(USAGE, file=sys.stderr)
        return 2
    rooms_path, bookings_path, day_text, output = argv
    day, error = parse_day(day_text)
    if not error:
        rooms, error = load_rooms(rooms_path)
    if not error:
        bookings, error = load_bookings(bookings_path)
    if not error:
        rows, error = build_agenda(rooms, bookings, day)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    write_agenda(rows, output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
