from datetime import datetime, timedelta

from sensorhub.readings import Reading, load_readings
from sensorhub.settings import Settings
from sensorhub.stats import count_gaps, group_by_sensor, sensor_stats


def reading(minute, sensor="a", value=1.0):
    return Reading(time=datetime(2026, 10, 1, 8, 0) + timedelta(minutes=minute), sensor=sensor,
                   value=value)


def test_group_by_sensor_keeps_order():
    groups = group_by_sensor([reading(0, "a"), reading(1, "b"), reading(2, "a")])
    assert [r.time.minute for r in groups["a"]] == [0, 2]
    assert list(groups) == ["a", "b"]


def test_count_gaps():
    group = [reading(0), reading(10), reading(50), reading(55)]
    assert count_gaps(group, timedelta(minutes=30)) == 1
    assert count_gaps(group, timedelta(minutes=5)) == 2


def test_sensor_stats(readings_file, capsys):
    readings, _ = load_readings(readings_file)
    stats = sensor_stats(readings, Settings(max_gap=30, min_readings=2))
    assert [item.sensor for item in stats] == ["boiler", "cellar"]
    boiler = stats[0]
    assert (boiler.count, boiler.low, boiler.high, boiler.gaps) == (4, 60.0, 66.5, 1)
    assert boiler.mean == 63.0
    assert boiler.last == datetime(2026, 10, 1, 9, 30)
    assert "attic: only 1 readings" in capsys.readouterr().out
