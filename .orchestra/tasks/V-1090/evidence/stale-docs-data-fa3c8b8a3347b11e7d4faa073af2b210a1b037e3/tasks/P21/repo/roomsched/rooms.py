"""Load the rooms file: name, capacity and opening hours of every room."""
import csv

from roomsched.clock import parse_time

ROOM_COLUMNS = ("name", "capacity", "opens", "closes")


def parse_room(row: dict[str, str]) -> tuple[dict | None, str | None]:
    """Build one room from a row of the rooms file.

    :param row: the raw row, keyed by column name.
    :returns: ``(room, None)`` or ``(None, message)``. A room has the keys ``name``,
        ``capacity``, ``opens`` and ``closes``; the times are minutes after midnight.
    """
    name = row["name"].strip()
    if not name:
        return None, "room without a name"
    capacity = row["capacity"].strip()
    if not capacity.isdigit() or int(capacity) < 1:
        return None, f"{name}: capacity must be a whole number above zero"
    opens, error = parse_time(row["opens"])
    if error:
        return None, f"{name}: {error}"
    closes, error = parse_time(row["closes"])
    if error:
        return None, f"{name}: {error}"
    if closes <= opens:
        return None, f"{name}: closes before it opens"
    return {"name": name, "capacity": int(capacity), "opens": opens, "closes": closes}, None


def load_rooms(path: str) -> tuple[dict[str, dict] | None, str | None]:
    """Read a rooms file.

    :param path: CSV file with the columns ``name,capacity,opens,closes``.
    :returns: ``(rooms, None)`` with the rooms keyed by name, or ``(None, message)``
        when the file cannot be read or a row is invalid.
    """
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            rows = list(reader)
    except OSError:
        return None, f"cannot read {path}"
    missing = [column for column in ROOM_COLUMNS if column not in header]
    if missing:
        return None, f"{path}: missing columns {', '.join(missing)}"
    rooms: dict[str, dict] = {}
    for line_no, row in enumerate(rows, start=2):
        if any(row.get(column) is None for column in ROOM_COLUMNS):
            return None, f"{path}:{line_no}: expected {len(ROOM_COLUMNS)} fields"
        room, error = parse_room(row)
        if error:
            return None, f"{path}:{line_no}: {error}"
        if room["name"] in rooms:
            return None, f"{path}:{line_no}: duplicate room {room['name']}"
        rooms[room["name"]] = room
    return rooms, None
