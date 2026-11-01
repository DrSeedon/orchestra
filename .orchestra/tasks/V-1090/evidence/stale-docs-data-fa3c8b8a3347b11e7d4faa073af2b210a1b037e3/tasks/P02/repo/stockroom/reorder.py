"""Decide which SKUs need a supplier order and how much to order."""
import logging

from stockroom.inventory import Inventory
from stockroom.models import OrderLine, ReorderRule, StockLevel

logger = logging.getLogger(__name__)


def needs_reorder(level: StockLevel, rule: ReorderRule) -> bool:
    """True when available stock is at or below the reorder point."""
    return level.available <= rule.reorder_point


def order_quantity(level: StockLevel, rule: ReorderRule) -> int:
    """Quantity to order: the rule's reorder quantity, capped by max_level."""
    if not needs_reorder(level, rule):
        return 0
    quantity = rule.reorder_qty
    if rule.max_level is not None:
        quantity = min(quantity, rule.max_level - level.on_hand)
    return max(quantity, 0)


def build_reorder_list(
    inventory: Inventory, rules: dict[str, ReorderRule], location: str
) -> list[OrderLine]:
    """Return one order line per SKU at ``location`` that needs restocking."""
    lines = []
    for level in inventory.levels_at(location):
        rule = rules.get(level.sku)
        if rule is None:
            logger.warning("no reorder rule for %s; skipped", level.sku)
            continue
        quantity = order_quantity(level, rule)
        if quantity > 0:
            lines.append(OrderLine(sku=level.sku, location=location, quantity=quantity))
    logger.info("%d order lines for %s", len(lines), location)
    return lines
