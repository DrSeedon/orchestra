import pytest

from stockroom.inventory import Inventory
from stockroom.models import StockLevel


def make_inventory():
    return Inventory([
        StockLevel("BOLT-10", "main", 50),
        StockLevel("NUT-10", "main", 5),
        StockLevel("BOLT-10", "shop", 4),
    ])


def test_get_level_creates_empty_level():
    inventory = Inventory()
    level = inventory.get_level("WASHER", "main")
    assert level.on_hand == 0
    assert inventory.get_level("WASHER", "main") is level


def test_add_stock():
    inventory = make_inventory()
    assert inventory.add_stock("NUT-10", "main", 20) == 25


def test_add_stock_rejects_non_positive():
    with pytest.raises(ValueError):
        make_inventory().add_stock("NUT-10", "main", 0)


def test_remove_stock():
    inventory = make_inventory()
    assert inventory.remove_stock("BOLT-10", "main", 30) == 20


def test_remove_stock_respects_reservations(caplog):
    inventory = make_inventory()
    inventory.reserve("BOLT-10", "shop", 3)
    with pytest.raises(ValueError, match="insufficient stock"):
        inventory.remove_stock("BOLT-10", "shop", 2)
    assert "only 1 available" in caplog.text


def test_reserve_more_than_available_fails():
    with pytest.raises(ValueError):
        make_inventory().reserve("NUT-10", "main", 6)


def test_locations_and_levels_at():
    inventory = make_inventory()
    assert inventory.locations() == {"main", "shop"}
    assert [level.sku for level in inventory.levels_at("main")] == ["BOLT-10", "NUT-10"]


def test_total_on_hand_sums_locations():
    assert make_inventory().total_on_hand("BOLT-10") == 54
