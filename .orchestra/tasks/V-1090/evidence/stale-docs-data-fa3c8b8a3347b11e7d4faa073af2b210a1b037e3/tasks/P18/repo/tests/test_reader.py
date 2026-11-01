import pytest

from csvmerge.errors import ColumnError, CsvReadError
from csvmerge.reader import read_table, sniff_delimiter


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_sniff_delimiter():
    assert sniff_delimiter("sku,name,price") == ","
    assert sniff_delimiter("sku;name;price") == ";"
    assert sniff_delimiter("sku\tname") == "\t"
    assert sniff_delimiter("sku") == ","


def test_read_table(tmp_path):
    path = write(tmp_path / "fruit.csv", "SKU,Name,Price\nA1, Apple ,1.20\n\nB2,Banana,0.50\n")
    table = read_table(path)
    assert table.name == "fruit.csv"
    assert table.columns == ["sku", "name", "price"]
    assert table.rows == [
        {"sku": "A1", "name": "Apple", "price": "1.20"},
        {"sku": "B2", "name": "Banana", "price": "0.50"},
    ]


def test_read_table_semicolons_and_bom(tmp_path):
    path = tmp_path / "export.csv"
    path.write_bytes(b"\xef\xbb\xbfsku;name\nA1;\"Apple; green\"\n")
    table = read_table(str(path))
    assert table.columns == ["sku", "name"]
    assert table.rows == [{"sku": "A1", "name": "Apple; green"}]


def test_header_only_file_has_no_rows(tmp_path):
    table = read_table(write(tmp_path / "empty_rows.csv", "sku,name\n"))
    assert table.columns == ["sku", "name"]
    assert table.rows == []


def test_empty_file(tmp_path):
    with pytest.raises(CsvReadError, match="empty"):
        read_table(write(tmp_path / "blank.csv", "\n  \n"))


def test_row_with_wrong_number_of_fields(tmp_path):
    path = write(tmp_path / "ragged.csv", "sku,name\nA1,Apple\nB2\n")
    with pytest.raises(CsvReadError, match="ragged.csv:3"):
        read_table(path)


def test_missing_file(tmp_path):
    with pytest.raises(CsvReadError, match="cannot read"):
        read_table(tmp_path / "missing.csv")


def test_bad_header(tmp_path):
    with pytest.raises(ColumnError):
        read_table(write(tmp_path / "twice.csv", "sku,SKU\nA1,A1\n"))
