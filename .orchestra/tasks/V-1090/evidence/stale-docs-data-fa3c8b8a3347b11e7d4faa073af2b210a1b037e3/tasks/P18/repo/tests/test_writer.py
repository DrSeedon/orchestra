from csvmerge.writer import write_table


def test_write_table_fills_missing_values(tmp_path):
    target = tmp_path / "out.csv"
    rows = [{"sku": "A1", "name": "Apple"}, {"sku": "B2", "stock": "4"}]
    assert write_table(target, ["sku", "name", "stock"], rows) == target
    assert target.read_text(encoding="utf-8").splitlines() == [
        "sku,name,stock",
        "A1,Apple,",
        "B2,,4",
    ]


def test_write_table_creates_folders(tmp_path):
    target = tmp_path / "reports" / "2024" / "out.csv"
    write_table(str(target), ["sku"], [])
    assert target.read_text(encoding="utf-8") == "sku\n"


def test_write_table_quotes_values(tmp_path):
    target = write_table(tmp_path / "out.csv", ["sku", "name"], [{"sku": "A1", "name": "Apple, green"}])
    assert target.read_text(encoding="utf-8").splitlines()[1] == 'A1,"Apple, green"'
