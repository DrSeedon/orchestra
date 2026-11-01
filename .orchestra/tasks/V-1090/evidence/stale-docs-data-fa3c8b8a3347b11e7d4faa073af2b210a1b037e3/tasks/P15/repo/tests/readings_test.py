import logging
from datetime import datetime

import pytest

from stationlog.readings import by_station, load_readings, parse_number

HEADER = "station,time,temp_c,humidity,pressure_hpa\n"


def write_csv(tmp_path, body, name="obs.csv"):
    target = tmp_path / name
    target.write_text(HEADER + body, encoding="utf-8")
    return str(target)


def test_parse_number_missing():
    assert parse_number("") is None
    assert parse_number(" NA ") is None
    assert parse_number("12.5") == 12.5


def test_load_sorts_and_skips_bad_rows(tmp_path, caplog):
    path = write_csv(
        tmp_path,
        "B2,2026-05-01T10:00,14.0,80,1012\n"
        "A1,2026-05-01T11:00,15.5,,1011\n"
        "A1,yesterday,1,1,1\n"
        "A1,2026-05-01T10:00,15.0,70,NA\n",
    )
    with caplog.at_level(logging.WARNING):
        readings = load_readings(path)
    assert [(r.station, r.time.hour) for r in readings] == [("A1", 10), ("A1", 11), ("B2", 10)]
    assert readings[0].pressure_hpa is None
    assert readings[1].humidity is None
    assert "line 4" in caplog.text


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_readings(str(tmp_path / "none.csv"))


def test_missing_columns(tmp_path):
    target = tmp_path / "bad.csv"
    target.write_text("station,time\nA1,2026-05-01T10:00\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_readings(str(target))


def test_by_station(tmp_path):
    path = write_csv(tmp_path, "A1,2026-05-01T10:00,1,1,1000\nB2,2026-05-01T10:00,2,2,1000\n")
    groups = by_station(load_readings(path))
    assert sorted(groups) == ["A1", "B2"]
    assert groups["B2"][0].time == datetime(2026, 5, 1, 10, 0)
