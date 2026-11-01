from roomsched.schedule import SLOT_BUSY, SLOT_FREE, day_slots, ranges_overlap

ROOM = {"name": "Aurora", "capacity": 8, "opens": 480, "closes": 1080}


def booking(booking_id, start, end):
    return {"id": booking_id, "start": start, "end": end}


def test_ranges_overlap_ignores_touching_ranges():
    assert ranges_overlap(540, 600, 570, 630)
    assert ranges_overlap(540, 600, 550, 560)
    assert not ranges_overlap(540, 600, 600, 660)
    assert not ranges_overlap(600, 660, 540, 600)


def test_day_slots_fills_gaps_with_free_slots():
    slots, error = day_slots(ROOM, [booking("B1", 540, 600), booking("B2", 600, 660)])
    assert error is None
    assert [(s["start"], s["end"], s["slot"], s["booking"]) for s in slots] == [
        ("08:00", "09:00", SLOT_FREE, ""),
        ("09:00", "10:00", SLOT_BUSY, "B1"),
        ("10:00", "11:00", SLOT_BUSY, "B2"),
        ("11:00", "18:00", SLOT_FREE, ""),
    ]


def test_day_slots_for_an_empty_day():
    slots, error = day_slots(ROOM, [])
    assert error is None
    assert slots == [{"start": "08:00", "end": "18:00", "slot": SLOT_FREE, "booking": ""}]


def test_day_slots_reports_overlapping_bookings():
    slots, error = day_slots(ROOM, [booking("B1", 540, 600), booking("B2", 570, 630)])
    assert slots is None
    assert "B2 overlaps B1" in error
