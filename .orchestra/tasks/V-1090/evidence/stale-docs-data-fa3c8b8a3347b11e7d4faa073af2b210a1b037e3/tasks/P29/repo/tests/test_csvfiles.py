from datetime import date

import pytest

from bookclub.csvfiles import parse_count, parse_day, read_rows


def test_read_rows_strips_values(write_file):
    path = write_file("x.csv", "a,b,extra\n 1 ,two,z\n3,,z\n")
    assert read_rows(path, ("a", "b")) == [(2, {"a": "1", "b": "two"}), (3, {"a": "3", "b": ""})]


def test_read_rows_missing_column(write_file):
    path = write_file("x.csv", "a\n1\n")
    with pytest.raises(ValueError, match="missing columns b"):
        read_rows(path, ("a", "b"))


def test_parse_day():
    assert parse_day("2026-09-14", "x.csv:2") == date(2026, 9, 14)
    with pytest.raises(ValueError, match="x.csv:2: bad date"):
        parse_day("14.09.2026", "x.csv:2")


def test_parse_count():
    assert parse_count("0", "x.csv:2") == 0
    with pytest.raises(ValueError, match="bad number"):
        parse_count("ten", "x.csv:2")
    with pytest.raises(ValueError, match="must not be negative"):
        parse_count("-3", "x.csv:2")
