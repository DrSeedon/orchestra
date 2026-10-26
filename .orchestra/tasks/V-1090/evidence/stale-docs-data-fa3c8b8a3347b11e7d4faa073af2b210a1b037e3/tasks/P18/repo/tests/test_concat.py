import pytest

from csvmerge.concat import concat_tables, main
from csvmerge.errors import ColumnError
from csvmerge.reader import Table


def test_concat_tables_keeps_file_order():
    first = Table("a.csv", ["sku", "name"], [{"sku": "A1", "name": "Apple"}])
    second = Table("b.csv", ["name", "sku"], [{"name": "Banana", "sku": "B2"}])
    assert concat_tables([first, second]) == [
        {"sku": "A1", "name": "Apple"},
        {"name": "Banana", "sku": "B2"},
    ]


def test_concat_tables_rejects_other_columns():
    first = Table("a.csv", ["sku", "name"])
    second = Table("b.csv", ["sku", "price"])
    with pytest.raises(ColumnError, match="b.csv has columns sku, price"):
        concat_tables([first, second])


def test_main_writes_output(tmp_path):
    (tmp_path / "a.csv").write_text("sku,name\nA1,Apple\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("name;sku\nBanana;B2\n", encoding="utf-8")
    output = tmp_path / "out" / "all.csv"
    assert main([str(output), str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]) == 0
    assert output.read_text(encoding="utf-8").splitlines() == ["sku,name", "A1,Apple", "B2,Banana"]


def test_main_fails_on_bad_input(tmp_path):
    (tmp_path / "a.csv").write_text("sku,name\nA1,Apple\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("sku,price\nB2,0.50\n", encoding="utf-8")
    output = tmp_path / "all.csv"
    assert main([str(output), str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]) == 2
    assert main([str(output), str(tmp_path / "a.csv"), str(tmp_path / "missing.csv")]) == 2
    assert not output.exists()
