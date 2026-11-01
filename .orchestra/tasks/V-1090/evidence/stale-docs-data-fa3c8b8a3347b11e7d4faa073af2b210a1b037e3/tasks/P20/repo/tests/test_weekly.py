from datetime import date

import pytest

from habitlog.entries import Entry
from habitlog.targets import Target
from habitlog.weekly import WeekRow, main, week_rows

LOG = """2024-04-28 run
2024-04-29 run
2024-04-30 run
2024-04-30 run
2024-05-02 read
2024-05-05 run
2024-05-06 run
"""


@pytest.fixture
def inputs(tmp_path):
    log = tmp_path / "habits.log"
    log.write_text(LOG, encoding="utf-8")
    targets = tmp_path / "targets.csv"
    targets.write_text("habit,per_week\nrun,3\nread,2\n", encoding="utf-8")
    return str(log), str(targets)


def test_week_row_met():
    assert WeekRow("run", 3, 3).met
    assert not WeekRow("run", 2, 3).met


def test_week_rows():
    entries = [Entry(date(2024, 4, 28), "run"), Entry(date(2024, 4, 29), "run"),
               Entry(date(2024, 5, 5), "run"), Entry(date(2024, 5, 1), "walk")]
    rows = week_rows(entries, [Target("read", 2), Target("run", 2)], date(2024, 5, 1))
    assert rows == [WeekRow("read", 0, 2), WeekRow("run", 2, 2)]


def test_main_with_day(inputs, tmp_path, capsys):
    output = tmp_path / "week.csv"
    assert main([*inputs, str(output), "--day", "2024-05-01"]) == 0
    assert output.read_text(encoding="utf-8").splitlines() == [
        "habit,done,target,met",
        "read,1,2,no",
        "run,3,3,yes",
    ]
    assert "week of 2024-04-29: 1 of 2 targets met" in capsys.readouterr().out


def test_main_default_day_is_last_log_day(inputs, tmp_path):
    output = tmp_path / "week.csv"
    assert main([*inputs, str(output)]) == 0
    assert output.read_text(encoding="utf-8").splitlines()[1:] == ["read,0,2,no", "run,1,3,no"]


def test_main_bad_day(inputs, tmp_path, capsys):
    output = tmp_path / "week.csv"
    assert main([*inputs, str(output), "--day", "2024-02-30"]) == 2
    assert not output.exists()
    assert "invalid day" in capsys.readouterr().err


def test_main_empty_log(inputs, tmp_path):
    log = tmp_path / "empty.log"
    log.write_text("# nothing yet\n", encoding="utf-8")
    output = tmp_path / "week.csv"
    assert main([str(log), inputs[1], str(output)]) == 2
    assert not output.exists()
