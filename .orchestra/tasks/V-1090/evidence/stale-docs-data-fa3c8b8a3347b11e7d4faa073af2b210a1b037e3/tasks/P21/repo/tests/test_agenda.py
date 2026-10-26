import csv

from roomsched.agenda import main

ROOMS = "name,capacity,opens,closes\nBorealis,4,09:00,12:00\nAurora,8,08:00,10:00\n"
BOOKINGS = (
    "id,room,date,start,end,attendees,status\n"
    "B1,Aurora,2026-03-02,08:30,09:00,3,confirmed\n"
    "B2,Aurora,2026-03-02,08:45,09:15,3,cancelled\n"
    "B3,Borealis,2026-03-03,09:00,10:00,2,confirmed\n"
)


def setup_files(tmp_path, bookings=BOOKINGS):
    rooms = tmp_path / "rooms.csv"
    rooms.write_text(ROOMS, encoding="utf-8")
    bookings_file = tmp_path / "bookings.csv"
    bookings_file.write_text(bookings, encoding="utf-8")
    return str(rooms), str(bookings_file)


def test_agenda_lists_every_room_for_the_day(tmp_path):
    rooms, bookings = setup_files(tmp_path)
    output = tmp_path / "agenda.csv"
    assert main([rooms, bookings, "2026-03-02", str(output)]) == 0
    with open(output, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["room", "start", "end", "slot", "booking"],
        ["Aurora", "08:00", "08:30", "free", ""],
        ["Aurora", "08:30", "09:00", "busy", "B1"],
        ["Aurora", "09:00", "10:00", "free", ""],
        ["Borealis", "09:00", "12:00", "free", ""],
    ]


def test_agenda_rejects_unknown_rooms(tmp_path, capsys):
    rooms, bookings = setup_files(tmp_path, BOOKINGS + "B4,Cupola,2026-03-02,09:00,10:00,2,confirmed\n")
    output = tmp_path / "agenda.csv"
    assert main([rooms, bookings, "2026-03-02", str(output)]) == 2
    assert not output.exists()
    assert "unknown room 'Cupola'" in capsys.readouterr().err


def test_agenda_rejects_bad_arguments(tmp_path, capsys):
    rooms, bookings = setup_files(tmp_path)
    assert main([rooms, bookings, "2026-03-02"]) == 2
    assert "usage" in capsys.readouterr().err
    assert main([rooms, bookings, "March 2", str(tmp_path / "out.csv")]) == 2
