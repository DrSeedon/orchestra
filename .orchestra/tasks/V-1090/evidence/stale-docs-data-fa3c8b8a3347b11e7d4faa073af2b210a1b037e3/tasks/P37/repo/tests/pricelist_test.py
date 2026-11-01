import pytest

from pricewatch.pricelist import PriceItem, loadPriceList, savePriceList


def write(tmp_path, text):
    path = tmp_path / "prices.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_keeps_file_order(tmp_path):
    path = write(tmp_path, "sku,name,price\nB-2,Stapler,8.25\nA-1,Desk lamp,20\n")
    items = loadPriceList(path)
    assert list(items) == ["B-2", "A-1"]
    assert items["A-1"] == PriceItem(sku="A-1", name="Desk lamp", price=2000)


def test_load_reports_missing_column(tmp_path):
    path = write(tmp_path, "sku,price\nA-1,20\n")
    with pytest.raises(ValueError, match="missing column name"):
        loadPriceList(path)


def test_load_reports_bad_price(tmp_path):
    path = write(tmp_path, "sku,name,price\nA-1,Desk lamp,twenty\n")
    with pytest.raises(ValueError, match="line 2: bad price"):
        loadPriceList(path)


def test_load_rejects_zero_price(tmp_path):
    path = write(tmp_path, "sku,name,price\nA-1,Desk lamp,0.00\n")
    with pytest.raises(ValueError, match="above zero"):
        loadPriceList(path)


def test_load_rejects_repeated_sku(tmp_path):
    path = write(tmp_path, "sku,name,price\nA-1,Desk lamp,20\nA-1,Lamp,21\n")
    with pytest.raises(ValueError, match="line 3: sku A-1 appears twice"):
        loadPriceList(path)


def test_save_and_load_round_trip(tmp_path):
    items = {
        "A-1": PriceItem(sku="A-1", name="Desk lamp", price=2000),
        "C-9": PriceItem(sku="C-9", name="Monitor arm", price=5249),
    }
    path = str(tmp_path / "out.csv")
    savePriceList(path, items)
    assert loadPriceList(path) == items
    with open(path, encoding="utf-8") as handle:
        assert handle.read().splitlines()[2] == "C-9,Monitor arm,52.49"
