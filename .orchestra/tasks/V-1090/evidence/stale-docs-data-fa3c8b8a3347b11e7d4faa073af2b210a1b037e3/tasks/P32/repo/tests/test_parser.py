import pytest

from cronlint.errors import CronRangeError, CronSyntaxError
from cronlint.fields import DAY, HOUR, MINUTE, MONTH, WEEKDAY
from cronlint.parser import expand_macro, parse_expression, parse_field


def test_parse_field_star_and_step():
    assert parse_field(MINUTE, "*/15") == {0, 15, 30, 45}
    assert parse_field(HOUR, "*") == set(range(24))


def test_parse_field_lists_ranges_and_names():
    assert parse_field(HOUR, "1-3,8") == {1, 2, 3, 8}
    assert parse_field(MONTH, "jan,Jul-aug") == {1, 7, 8}
    assert parse_field(WEEKDAY, "mon-fri") == {1, 2, 3, 4, 5}


def test_parse_field_start_with_step_runs_to_end():
    assert parse_field(DAY, "25/3") == {25, 28, 31}


def test_weekday_seven_is_sunday():
    assert parse_field(WEEKDAY, "5-7") == {0, 5, 6}


@pytest.mark.parametrize("field, text", [(MINUTE, "60"), (MONTH, "0"), (WEEKDAY, "8"), (HOUR, "5-2")])
def test_parse_field_rejects_bad_ranges(field, text):
    with pytest.raises(CronRangeError):
        parse_field(field, text)


@pytest.mark.parametrize("text", ["x", "1,,2", "*/0", "*/a"])
def test_parse_field_rejects_bad_syntax(text):
    with pytest.raises(CronSyntaxError):
        parse_field(MINUTE, text)


def test_expand_macro():
    assert expand_macro(" @Daily ") == "0 0 * * *"
    assert expand_macro(" 5 * * * * ") == "5 * * * *"
    with pytest.raises(CronSyntaxError, match="unknown macro"):
        expand_macro("@sometimes")


def test_parse_expression_fields_and_stars():
    schedule = parse_expression("30 2 1,15 * mon")
    assert schedule.values[MINUTE] == {30}
    assert schedule.values[DAY] == {1, 15}
    assert schedule.values[WEEKDAY] == {1}
    assert not schedule.day_star
    assert not schedule.weekday_star
    assert parse_expression("@weekly").expression == "@weekly"


def test_parse_expression_needs_five_fields():
    with pytest.raises(CronSyntaxError, match="expected 5 fields"):
        parse_expression("* * * *")
