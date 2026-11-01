from datetime import datetime

from sensorhub.readings import Reading, load_readings, parse_reading


def test_load_readings_sorts_by_time_and_skips_bad_rows(readings_file, capsys):
    readings, error = load_readings(readings_file)
    assert error is None
    assert len(readings) == 7
    assert readings[0] == Reading(time=datetime(2026, 10, 1, 8, 0), sensor="boiler", value=61.5)
    assert readings[-1].time == datetime(2026, 10, 1, 9, 30)
    assert "readings.csv:9: bad time 'noon', row skipped" in capsys.readouterr().out


def test_parse_reading_errors():
    assert parse_reading({"time": "2026-10-01T08:00:00", "sensor": "", "value": "1"}) == (
        None, "sensor is empty")
    reading, error = parse_reading({"time": "2026-10-01T08:00:00", "sensor": "a", "value": "warm"})
    assert reading is None
    assert error == "bad value 'warm'"


def test_missing_column(write_file):
    path = write_file("r.csv", "time,sensor\n2026-10-01T08:00:00,a\n")
    readings, error = load_readings(path)
    assert readings is None
    assert "missing columns value" in error


def test_missing_file(tmp_path):
    readings, error = load_readings(str(tmp_path / "none.csv"))
    assert readings is None
    assert error.startswith("cannot read")
