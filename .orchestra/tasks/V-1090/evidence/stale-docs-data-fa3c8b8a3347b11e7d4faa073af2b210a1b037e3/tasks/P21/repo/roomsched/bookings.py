"""Load bookings files and pick out the bookings that are in effect."""
import csv

from roomsched.clock import parse_day, parse_time

STATUS_CONFIRMED = "confirmed"
STATUS_TENTATIVE = "tentative"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_CONFIRMED, STATUS_TENTATIVE, STATUS_CANCELLED)

BOOKING_COLUMNS = ("id", "room", "date", "start", "end", "attendees", "status")


def parse_booking(row: dict[str, str]) -> tuple[dict | None, str | None]:
    """Build one booking from a row of a bookings file.

    :param row: the raw row, keyed by column name.
    :returns: ``(booking, None)`` or ``(None, message)``. The booking keeps the
        column names as keys; ``start`` and ``end`` are minutes after midnight and
        ``attendees`` is an int.
    """
    booking_id = row["id"].strip()
    if not booking_id:
        return None, "booking without an id"
    day, error = parse_day(row["date"])
    if error:
        return None, f"{booking_id}: {error}"
    start, error = parse_time(row["start"])
    if error:
        return None, f"{booking_id}: {error}"
    end, error = parse_time(row["end"])
    if error:
        return None, f"{booking_id}: {error}"
    if end <= start:
        return None, f"{booking_id}: ends before it starts"
    attendees = row["attendees"].strip()
    if not attendees.isdigit():
        return None, f"{booking_id}: attendees must be a whole number"
    status = row["status"].strip().lower()
    if status not in STATUSES:
        return None, f"{booking_id}: unknown status {status!r}"
    booking = {
        "id": booking_id,
        "room": row["room"].strip(),
        "date": day,
        "start": start,
        "end": end,
        "attendees": int(attendees),
        "status": status,
    }
    return booking, None


def load_bookings(path: str) -> tuple[list[dict] | None, str | None]:
    """Read a bookings file.

    :param path: CSV file with the columns ``id,room,date,start,end,attendees,status``.
    :returns: ``(bookings, None)`` in file order, or ``(None, message)`` when the file
        cannot be read, a row is invalid or a booking id appears twice.
    """
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            rows = list(reader)
    except OSError:
        return None, f"cannot read {path}"
    missing = [column for column in BOOKING_COLUMNS if column not in header]
    if missing:
        return None, f"{path}: missing columns {', '.join(missing)}"
    bookings = []
    seen = set()
    for line_no, row in enumerate(rows, start=2):
        if any(row.get(column) is None for column in BOOKING_COLUMNS):
            return None, f"{path}:{line_no}: expected {len(BOOKING_COLUMNS)} fields"
        booking, error = parse_booking(row)
        if error:
            return None, f"{path}:{line_no}: {error}"
        if booking["id"] in seen:
            return None, f"{path}:{line_no}: duplicate booking id {booking['id']}"
        seen.add(booking["id"])
        bookings.append(booking)
    return bookings, None


def active_bookings(bookings: list[dict]) -> list[dict]:
    """Drop cancelled bookings.

    :param bookings: bookings as returned by ``load_bookings``.
    :returns: the confirmed and tentative bookings, in their original order.
    """
    return [booking for booking in bookings if booking["status"] != STATUS_CANCELLED]


def bookings_for(bookings: list[dict], room: str, day: str) -> list[dict]:
    """Pick the bookings of one room on one day.

    :param bookings: the bookings to search.
    :param room: the room name.
    :param day: the day in ISO form.
    :returns: the matching bookings, sorted by start and end time.
    """
    found = [b for b in bookings if b["room"] == room and b["date"] == day]
    return sorted(found, key=lambda booking: (booking["start"], booking["end"]))
