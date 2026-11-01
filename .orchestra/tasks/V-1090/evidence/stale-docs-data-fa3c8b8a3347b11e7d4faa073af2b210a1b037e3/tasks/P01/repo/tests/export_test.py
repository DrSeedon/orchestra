import os

import pytest

from invoice_tool.export import output_path, write_records

RECORD = {
    "supplier": "acme",
    "invoice_no": "A-1",
    "date": "2024-03-01",
    "amount_cents": 1000,
    "currency": "EUR",
}


def test_output_path():
    assert output_path("out", "march") == os.path.join("out", "march.csv")


def test_write_records_creates_folder_and_file(tmp_path, capsys):
    out_dir = os.path.join(str(tmp_path), "out")
    target = write_records([RECORD], out_dir, "march")
    assert target == os.path.join(out_dir, "march.csv")
    with open(target, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert lines == [
        "supplier,invoice_no,date,amount_cents,currency",
        "acme,A-1,2024-03-01,1000,EUR",
    ]
    assert "wrote 1 records" in capsys.readouterr().out


def test_write_records_rejects_empty_list(tmp_path):
    with pytest.raises(ValueError):
        write_records([], str(tmp_path))
