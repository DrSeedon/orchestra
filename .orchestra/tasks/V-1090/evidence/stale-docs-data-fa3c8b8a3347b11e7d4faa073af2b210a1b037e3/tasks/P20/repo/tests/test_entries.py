from datetime import date

import pytest

from habitlog.entries import Entry, parse_line, read_log
from habitlog.stats import days_by_habit, entries_between, last_day

LOG = """# May
2024-05-02 Run
2024-05-01 read

2024-05-01  run
2024-05-02 run
2024-05-03 evening   walk
"""


def test_parse_line():
    assert parse_line("2024-05-01  Morning   Run\n") == Entry(date(2024, 5, 1), "morning run")


@pytest.mark.parametrize("line", ["", "   \n", "# comment"])
def test_parse_line_skipped(line):
    assert parse_line(line) is None


def test_parse_line_missing_habit():
    with pytest.raises(ValueError, match="missing habit name"):
        parse_line("2024-05-01")


def test_read_log(tmp_path):
    path = tmp_path / "habits.log"
    path.write_text(LOG, encoding="utf-8")
    entries = read_log(str(path))
    assert [entry.habit for entry in entries] == ["run", "read", "run", "run", "evening walk"]
    assert entries[0].day == date(2024, 5, 2)


def test_read_log_bad_line(tmp_path):
    path = tmp_path / "habits.log"
    path.write_text("2024-05-01 run\n2024-13-01 run\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"habits.log:2: invalid day"):
        read_log(str(path))


def test_entries_between():
    entries = [Entry(date(2024, 5, day), "run") for day in (1, 3, 5)]
    assert entries_between(entries, date(2024, 5, 2), date(2024, 5, 5)) == entries[1:]
    assert entries_between(entries, last=date(2024, 5, 3)) == entries[:2]
    assert entries_between(entries) == entries


def test_days_by_habit():
    entries = [
        Entry(date(2024, 5, 2), "run"),
        Entry(date(2024, 5, 1), "read"),
        Entry(date(2024, 5, 1), "run"),
        Entry(date(2024, 5, 2), "run"),
    ]
    result = days_by_habit(entries)
    assert list(result) == ["read", "run"]
    assert result["run"] == [date(2024, 5, 1), date(2024, 5, 2)]


def test_last_day():
    entries = [Entry(date(2024, 5, 3), "run"), Entry(date(2024, 5, 1), "read")]
    assert last_day(entries) == date(2024, 5, 3)
    assert last_day([]) is None
