from roomsched.bookings import STATUS_CANCELLED, active_bookings, bookings_for, load_bookings

HEADER = "id,room,date,start,end,attendees,status\n"


def write(path, text):
    path.write_text(HEADER + text, encoding="utf-8")
    return str(path)


def test_load_bookings_keeps_file_order(tmp_path):
    path = write(
        tmp_path / "b.csv",
        "B2,Aurora,2026-03-02,10:00,11:00,3,Confirmed\nB1,Aurora,2026-03-02,09:00,10:00,2,tentative\n",
    )
    bookings, error = load_bookings(path)
    assert error is None
    assert [b["id"] for b in bookings] == ["B2", "B1"]
    assert bookings[0] == {
        "id": "B2", "room": "Aurora", "date": "2026-03-02",
        "start": 600, "end": 660, "attendees": 3, "status": "confirmed",
    }


def test_load_bookings_rejects_bad_rows(tmp_path):
    cases = [
        ("B1,Aurora,2026-03-02,10:00,09:00,3,confirmed\n", "ends before it starts"),
        ("B1,Aurora,2026-03-02,09:00,10:00,many,confirmed\n", "attendees"),
        ("B1,Aurora,2026-03-02,09:00,10:00,3,maybe\n", "unknown status"),
        ("B1,Aurora,2026-03-02,09:00,10:00,3,confirmed\nB1,Aurora,2026-03-03,09:00,10:00,3,confirmed\n",
         "duplicate booking id"),
    ]
    for text, expected in cases:
        bookings, error = load_bookings(write(tmp_path / "b.csv", text))
        assert bookings is None
        assert expected in error


def test_active_bookings_drops_cancelled(tmp_path):
    path = write(
        tmp_path / "b.csv",
        "B1,Aurora,2026-03-02,09:00,10:00,2,cancelled\nB2,Aurora,2026-03-02,09:00,10:00,2,tentative\n",
    )
    bookings, _ = load_bookings(path)
    assert bookings[0]["status"] == STATUS_CANCELLED
    assert [b["id"] for b in active_bookings(bookings)] == ["B2"]


def test_bookings_for_filters_and_sorts(tmp_path):
    path = write(
        tmp_path / "b.csv",
        "B1,Aurora,2026-03-02,13:00,14:00,2,confirmed\n"
        "B2,Borealis,2026-03-02,09:00,10:00,2,confirmed\n"
        "B3,Aurora,2026-03-02,09:00,10:00,2,confirmed\n"
        "B4,Aurora,2026-03-03,08:00,09:00,2,confirmed\n",
    )
    bookings, _ = load_bookings(path)
    assert [b["id"] for b in bookings_for(bookings, "Aurora", "2026-03-02")] == ["B3", "B1"]
