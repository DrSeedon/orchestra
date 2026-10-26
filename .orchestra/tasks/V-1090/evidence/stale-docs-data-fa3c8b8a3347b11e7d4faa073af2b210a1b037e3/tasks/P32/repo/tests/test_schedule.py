from datetime import date, datetime

from cronlint.fields import HOUR, MINUTE
from cronlint.parser import parse_expression


def test_is_full():
    schedule = parse_expression("*/1 9 * * *")
    assert schedule.is_full(MINUTE)
    assert not schedule.is_full(HOUR)


def test_times_are_sorted():
    assert parse_expression("45,15 18,6 * * *").times() == [(6, 15), (6, 45), (18, 15), (18, 45)]


def test_matches():
    schedule = parse_expression("0 9 * * mon-fri")
    assert schedule.matches(datetime(2026, 1, 5, 9, 0))
    assert not schedule.matches(datetime(2026, 1, 4, 9, 0))
    assert not schedule.matches(datetime(2026, 1, 5, 9, 1))


def test_day_and_weekday_either_matches_when_both_restricted():
    schedule = parse_expression("0 0 13 * fri")
    assert schedule.matches_day(date(2026, 1, 13))
    assert schedule.matches_day(date(2026, 1, 2))
    assert not schedule.matches_day(date(2026, 1, 3))


def test_day_and_weekday_both_match_when_one_is_star():
    schedule = parse_expression("0 0 */2 * mon")
    assert schedule.matches_day(date(2026, 1, 12)) is False
    assert schedule.matches_day(date(2026, 1, 19)) is True


def test_next_run_same_day_and_later():
    schedule = parse_expression("30 8,17 * * *")
    assert schedule.next_run(datetime(2026, 3, 1, 9, 0)) == datetime(2026, 3, 1, 17, 30)
    assert schedule.next_run(datetime(2026, 3, 1, 17, 30, 45)) == datetime(2026, 3, 1, 17, 30)
    assert schedule.next_run(datetime(2026, 3, 1, 18, 0)) == datetime(2026, 3, 2, 8, 30)


def test_next_run_finds_leap_day():
    schedule = parse_expression("0 0 29 2 *")
    assert schedule.next_run(datetime(2026, 3, 1)) == datetime(2028, 2, 29)


def test_next_run_none_when_never():
    assert parse_expression("0 0 31 4 *").next_run(datetime(2026, 1, 1), max_days=800) is None


def test_runs():
    runs = parse_expression("0 */12 * * *").runs(datetime(2026, 1, 1, 6, 0), 3)
    assert runs == [datetime(2026, 1, 1, 12), datetime(2026, 1, 2, 0), datetime(2026, 1, 2, 12)]
    assert parse_expression("0 0 30 2 *").runs(datetime(2026, 1, 1), 2) == []
