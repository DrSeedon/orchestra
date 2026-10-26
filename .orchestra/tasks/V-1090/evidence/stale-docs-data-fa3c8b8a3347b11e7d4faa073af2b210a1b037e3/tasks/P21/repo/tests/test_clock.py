from roomsched.clock import format_time, parse_day, parse_time


def test_parse_time_gives_minutes_after_midnight():
    assert parse_time("09:30") == (570, None)
    assert parse_time(" 00:00 ") == (0, None)
    assert parse_time("24:00") == (1440, None)


def test_parse_time_rejects_bad_text():
    for text in ("9:30", "09:60", "25:00", "24:01", "noon", "09-30"):
        minutes, error = parse_time(text)
        assert minutes is None
        assert "not a time" in error


def test_format_time_pads_hours_and_minutes():
    assert format_time(570) == "09:30"
    assert format_time(5) == "00:05"
    assert format_time(1440) == "24:00"


def test_parse_day_accepts_iso_days_only():
    assert parse_day("2026-03-02") == ("2026-03-02", None)
    day, error = parse_day("2026-02-30")
    assert day is None and "not a day" in error
    day, error = parse_day("20260302")
    assert day is None and "not a day" in error
