import logging

from stockroom.inventory import Inventory
from stockroom.models import OrderLine, ReorderRule, StockLevel
from stockroom.reorder import build_reorder_list, needs_reorder, order_quantity

RULE = ReorderRule(sku="NUT-10", reorder_point=10, reorder_qty=100)


def test_needs_reorder_at_or_below_point():
    assert needs_reorder(StockLevel("NUT-10", "main", 10), RULE)
    assert not needs_reorder(StockLevel("NUT-10", "main", 11), RULE)


def test_needs_reorder_counts_reserved_stock():
    assert needs_reorder(StockLevel("NUT-10", "main", 15, reserved=6), RULE)


def test_order_quantity_uses_reorder_qty():
    assert order_quantity(StockLevel("NUT-10", "main", 4), RULE) == 100
    assert order_quantity(StockLevel("NUT-10", "main", 40), RULE) == 0


def test_order_quantity_capped_by_max_level():
    rule = ReorderRule(sku="NUT-10", reorder_point=10, reorder_qty=100, max_level=60)
    assert order_quantity(StockLevel("NUT-10", "main", 5), rule) == 55


def test_build_reorder_list(caplog):
    caplog.set_level(logging.INFO)
    inventory = Inventory([
        StockLevel("NUT-10", "main", 3),
        StockLevel("BOLT-10", "main", 500),
        StockLevel("PIN-2", "main", 0),
    ])
    rules = {"NUT-10": RULE, "BOLT-10": ReorderRule("BOLT-10", 50, 200)}
    lines = build_reorder_list(inventory, rules, "main")
    assert lines == [OrderLine(sku="NUT-10", location="main", quantity=100)]
    assert "no reorder rule for PIN-2" in caplog.text
