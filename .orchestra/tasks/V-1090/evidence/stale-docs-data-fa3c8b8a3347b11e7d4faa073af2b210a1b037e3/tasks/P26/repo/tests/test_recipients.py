import logging

import pytest

from mailmerge.recipients import clean_columns, load_recipients, normalize_email


def test_normalize_email():
    assert normalize_email("  Ann@Example.COM ") == "ann@example.com"
    assert normalize_email("not-an-address") is None
    assert normalize_email("a@b") is None


def test_clean_columns():
    assert clean_columns([" Email", "NAME ", "City"]) == ["email", "name", "city"]


def test_load_recipients(write_file):
    path = write_file("people.csv", "Email,Name,City\nann@example.com,Ann,Oslo\n\nbo@example.com,Bo\n")
    assert load_recipients(path) == [
        {"email": "ann@example.com", "name": "Ann", "city": "Oslo"},
        {"email": "bo@example.com", "name": "Bo", "city": ""},
    ]


def test_load_recipients_skips_bad_and_repeated_rows(write_file, caplog):
    text = "email,name\nann@example.com,Ann\nnope,Bob\nANN@example.com,Ann again\n"
    with caplog.at_level(logging.INFO):
        recipients = load_recipients(write_file("people.csv", text))
    assert [r["name"] for r in recipients] == ["Ann"]
    assert "people.csv:3: bad address 'nope', row skipped" in caplog.text
    assert "people.csv:4: ann@example.com is listed twice" in caplog.text
    assert "read 1 recipients" in caplog.text


def test_load_recipients_needs_email_column(write_file):
    with pytest.raises(ValueError, match="no email column"):
        load_recipients(write_file("people.csv", "name\nAnn\n"))


def test_load_recipients_empty_file(write_file):
    with pytest.raises(ValueError, match="empty"):
        load_recipients(write_file("people.csv", ""))
