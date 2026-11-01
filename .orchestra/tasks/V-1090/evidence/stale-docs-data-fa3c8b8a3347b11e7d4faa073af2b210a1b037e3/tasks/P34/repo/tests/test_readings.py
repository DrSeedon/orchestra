from datetime import date

import pytest

from meterread.readings import Reading, check_meter, group_by_meter, load_readings, parse_row


def test_parse_row():
    row = {"meter": " M1 ", "date": "2026-03-01", "kwh": "1520"}
    assert parse_row(row) == (Reading("M1", date(2026, 3, 1), 1520), None)


@pytest.mark.parametrize("row, message", [
    ({"meter": "", "date": "2026-03-01", "kwh": "1"}, "no meter id"),
    ({"meter": "M1", "date": "01.03.2026", "kwh": "1"}, "bad date"),
    ({"meter": "M1", "date": "2026-03-01", "kwh": "12.5"}, "bad meter value"),
    ({"meter": "M1", "date": "2026-03-01", "kwh": None}, "bad meter value"),
])
def test_parse_row_rejects(row, message):
    reading, error = parse_row(row)
    assert reading is None
    assert error.startswith(message)


def test_load_readings(tmp_path):
    path = tmp_path / "readings.csv"
    path.write_text("meter,date,kwh\nM1,2026-03-01,100\nM2,2026-03-01,7\n", encoding="utf-8")
    readings, error = load_readings(str(path))
    assert error is None
    assert [r.meter for r in readings] == ["M1", "M2"]


def test_load_readings_reports_line(tmp_path):
    path = tmp_path / "readings.csv"
    path.write_text("meter,date,kwh\nM1,2026-03-01,100\nM1,2026-03-xx,120\n", encoding="utf-8")
    readings, error = load_readings(str(path))
    assert readings is None
    assert error.endswith("line 3: bad date '2026-03-xx'")


def test_load_readings_checks_header(tmp_path):
    path = tmp_path / "readings.csv"
    path.write_text("meter,day,kwh\n", encoding="utf-8")
    readings, error = load_readings(str(path))
    assert readings is None
    assert "the header must be meter,date,kwh" in error


def test_group_by_meter_sorts_by_day():
    readings = [
        Reading("M2", date(2026, 3, 5), 50),
        Reading("M1", date(2026, 3, 9), 130),
        Reading("M1", date(2026, 3, 1), 100),
    ]
    groups = group_by_meter(readings)
    assert list(groups) == ["M2", "M1"]
    assert [r.kwh for r in groups["M1"]] == [100, 130]


def test_check_meter():
    good = [Reading("M1", date(2026, 3, 1), 100), Reading("M1", date(2026, 3, 2), 100)]
    assert check_meter(good) is None
    lower = [Reading("M1", date(2026, 3, 1), 100), Reading("M1", date(2026, 3, 2), 99)]
    assert "lower than the one before" in check_meter(lower)
    same_day = [Reading("M1", date(2026, 3, 1), 100), Reading("M1", date(2026, 3, 1), 101)]
    assert "two readings on 2026-03-01" in check_meter(same_day)
