import csv
from datetime import date, datetime

from stationlog.daily import daily_summaries, mean
from stationlog.export import summary_path, write_summaries
from stationlog.readings import Reading


def reading(station, hour, temp, hum=None, day=1):
    return Reading(station, datetime(2026, 5, day, hour, 0), temp, hum, 1000.0)


READINGS = [
    reading("A1", 6, 10.0, 80.0),
    reading("A1", 12, 18.0, 60.0),
    reading("A1", 18, None, None),
    reading("A1", 6, 9.0, day=2),
    reading("B2", 6, None),
]


def test_mean():
    assert mean([]) is None
    assert mean([1.0, 2.0, 2.0]) == 1.7


def test_daily_summaries():
    out = daily_summaries(READINGS)
    assert [(s.station, s.day) for s in out] == [
        ("A1", date(2026, 5, 1)),
        ("A1", date(2026, 5, 2)),
        ("B2", date(2026, 5, 1)),
    ]
    first = out[0]
    assert (first.count, first.temp_min, first.temp_max, first.temp_mean) == (3, 10.0, 18.0, 14.0)
    assert first.humidity_mean == 70.0
    assert out[2].temp_mean is None


def test_summary_path_default_and_out_dir():
    assert summary_path("data/north.csv").replace("\\", "/") == "data/north.daily.csv"
    assert summary_path("data/north.csv", "out").replace("\\", "/") == "out/north.daily.csv"


def test_write_summaries(tmp_path):
    target = str(tmp_path / "sub" / "north.daily.csv")
    write_summaries(daily_summaries(READINGS), target)
    with open(target, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "station"
    assert rows[1] == ["A1", "2026-05-01", "3", "10.0", "18.0", "14.0", "70.0"]
    assert rows[3][5] == ""
