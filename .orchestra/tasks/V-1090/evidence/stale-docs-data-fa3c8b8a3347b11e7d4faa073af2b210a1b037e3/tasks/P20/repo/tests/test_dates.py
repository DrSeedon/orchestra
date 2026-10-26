from datetime import date

import pytest

from habitlog.dates import parse_day, week_days, week_start


def test_parse_day():
    assert parse_day(" 2024-05-01 ") == date(2024, 5, 1)


@pytest.mark.parametrize("text", ["2024-5-1", "20240501", "2024-02-30", "yesterday", ""])
def test_parse_day_invalid(text):
    with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
        parse_day(text)


def test_week_start():
    assert week_start(date(2024, 5, 1)) == date(2024, 4, 29)
    assert week_start(date(2024, 4, 29)) == date(2024, 4, 29)
    assert week_start(date(2024, 5, 5)) == date(2024, 4, 29)


def test_week_days():
    days = week_days(date(2024, 5, 3))
    assert len(days) == 7
    assert days[0] == date(2024, 4, 29)
    assert days[-1] == date(2024, 5, 5)
