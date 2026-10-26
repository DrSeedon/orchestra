from datetime import date

import pytest

from plantcare.history import append_history, read_history


def test_append_and_read(tmp_path):
    path = tmp_path / "logs" / "history.txt"
    append_history(path, date(2026, 7, 1), ["Fern", "Basil"])
    append_history(path, date(2026, 7, 2), ["Basil"])
    assert read_history(path) == [
        (date(2026, 7, 1), "Fern"),
        (date(2026, 7, 1), "Basil"),
        (date(2026, 7, 2), "Basil"),
    ]


def test_missing_history_is_empty(tmp_path):
    assert read_history(tmp_path / "history.txt") == []


def test_bad_date(tmp_path):
    path = tmp_path / "history.txt"
    path.write_text("2026-07-01 Fern\nyesterday Basil\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_history(path)
