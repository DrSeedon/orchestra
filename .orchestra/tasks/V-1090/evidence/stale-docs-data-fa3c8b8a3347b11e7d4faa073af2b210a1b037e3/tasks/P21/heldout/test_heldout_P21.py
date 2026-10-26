import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOMS = "name,capacity,opens,closes\nAurora,8,08:00,18:00\nBorealis,4,09:00,17:00\n"
HEADER = "id,room,date,start,end,attendees,status\n"
BOOKINGS = HEADER + (
    "B1,Aurora,2026-03-02,09:00,10:00,6,confirmed\n"
    "B2,Aurora,2026-03-02,09:30,10:30,4,tentative\n"
    "B3,Aurora,2026-03-02,10:00,11:00,3,confirmed\n"
    "B4,Borealis,2026-03-02,08:30,09:30,6,confirmed\n"
    "B5,Aurora,2026-03-02,09:15,09:45,2,cancelled\n"
    "B6,Aurora,2026-03-03,09:00,10:00,9,confirmed\n"
    "B7,Aurora,2026-03-02,09:45,18:30,2,confirmed\n"
)


def run(tmp_path, rooms_text, bookings_text):
    rooms = tmp_path / "rooms.csv"
    rooms.write_text(rooms_text, encoding="utf-8")
    bookings = tmp_path / "bookings.csv"
    if bookings_text is not None:
        bookings.write_text(bookings_text, encoding="utf-8")
    output = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-m", "roomsched.conflicts", str(rooms), str(bookings), str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    return result, output


def entry(booking, kind, other=None):
    return {"booking": booking, "kind": kind, "other": other}


def test_conflicts_report(tmp_path):
    result, output = run(tmp_path, ROOMS, BOOKINGS)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == {
        "conflicts": [
            entry("B2", "overlap", "B1"),
            entry("B3", "overlap", "B2"),
            entry("B4", "hours"),
            entry("B4", "capacity"),
            entry("B6", "capacity"),
            entry("B7", "overlap", "B1"),
            entry("B7", "overlap", "B2"),
            entry("B7", "overlap", "B3"),
            entry("B7", "hours"),
        ],
        "counts": {"overlap": 5, "hours": 2, "capacity": 2},
    }


def test_no_conflicts(tmp_path):
    bookings = HEADER + (
        "C1,Aurora,2026-03-02,08:00,10:00,8,confirmed\n"
        "C2,Aurora,2026-03-02,10:00,12:00,8,tentative\n"
        "C3,Aurora,2026-03-02,09:00,11:00,20,cancelled\n"
        "C4,Borealis,2026-03-02,09:00,17:00,4,confirmed\n"
    )
    result, output = run(tmp_path, ROOMS, bookings)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == {"conflicts": [], "counts": {"overlap": 0, "hours": 0, "capacity": 0}}


def test_unknown_room_is_an_error(tmp_path):
    bookings = BOOKINGS + "B8,Cupola,2026-03-02,09:00,10:00,2,confirmed\n"
    result, output = run(tmp_path, ROOMS, bookings)
    assert result.returncode == 2
    assert not output.exists()


def test_missing_bookings_file(tmp_path):
    result, output = run(tmp_path, ROOMS, None)
    assert result.returncode == 2
    assert not output.exists()
