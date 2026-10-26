import os

import pytest

from invoice_tool.parser import canonical_column, read_invoice_csv


def test_canonical_column_maps_aliases():
    assert canonical_column(" Invoice Number ") == "invoice_no"
    assert canonical_column("CCY") == "currency"
    assert canonical_column("Due Date") == "due_date"


def test_read_invoice_csv_returns_rows(write_file):
    path = write_file("acme.csv", "Invoice,Date,Total,CCY\nA-1,2024-03-01,10.00,EUR\n")
    rows = read_invoice_csv(path)
    assert rows == [
        {"invoice_no": "A-1", "date": "2024-03-01", "amount": "10.00", "currency": "EUR"}
    ]


def test_read_invoice_csv_semicolon_delimiter(write_file):
    path = write_file("globex.csv", "invoice_no;date;amount;currency\nG-9;01.03.2024;12,5;EUR\n")
    rows = read_invoice_csv(path, delimiter=";")
    assert rows[0]["amount"] == "12,5"


def test_read_invoice_csv_skips_short_and_blank_rows(write_file, capsys):
    text = "invoice_no,date,amount,currency\nA-1,2024-03-01,10.00\n,,,\nA-2,2024-03-02,5.00,EUR\n"
    rows = read_invoice_csv(write_file("acme.csv", text))
    assert [row["invoice_no"] for row in rows] == ["A-2"]
    assert "acme.csv:2: expected 4 fields, got 3; row skipped" in capsys.readouterr().out


def test_read_invoice_csv_missing_columns(write_file):
    path = write_file("acme.csv", "invoice_no,date\nA-1,2024-03-01\n")
    with pytest.raises(ValueError, match="missing columns amount, currency"):
        read_invoice_csv(path)


def test_read_invoice_csv_empty_file(write_file):
    with pytest.raises(ValueError, match="empty"):
        read_invoice_csv(write_file("acme.csv", ""))


def test_read_invoice_csv_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_invoice_csv(os.path.join(str(tmp_path), "nope.csv"))
