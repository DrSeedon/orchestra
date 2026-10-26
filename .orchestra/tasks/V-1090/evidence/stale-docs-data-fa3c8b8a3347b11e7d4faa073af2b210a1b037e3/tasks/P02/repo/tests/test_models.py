from stockroom.models import StockLevel


def test_available_subtracts_reserved():
    level = StockLevel(sku="BOLT-10", location="main", on_hand=40, reserved=15)
    assert level.available == 25


def test_new_level_has_nothing_reserved():
    assert StockLevel(sku="BOLT-10", location="main", on_hand=3).reserved == 0
