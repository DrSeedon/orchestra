"""Load stock levels and reorder rules from CSV exports."""
import csv
import logging

from stockroom.models import ReorderRule, StockLevel

logger = logging.getLogger(__name__)


def parse_quantity(text: str) -> int:
    """Parse a whole, non-negative quantity."""
    value = int(text.strip())
    if value < 0:
        raise ValueError(f"negative quantity: {value}")
    return value


def load_levels_csv(path: str) -> list[StockLevel]:
    """Read rows of sku,location,on_hand[,reserved]; bad rows are skipped."""
    levels = []
    with open(path, newline="", encoding="utf-8") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            try:
                levels.append(
                    StockLevel(
                        sku=row["sku"].strip(),
                        location=row["location"].strip(),
                        on_hand=parse_quantity(row["on_hand"]),
                        reserved=parse_quantity(row.get("reserved") or "0"),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("%s:%d: skipped level row (%s)", path, line_no, exc)
    return levels


def load_rules_csv(path: str) -> dict[str, ReorderRule]:
    """Read rows of sku,reorder_point,reorder_qty[,max_level] keyed by SKU."""
    rules = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            try:
                max_text = (row.get("max_level") or "").strip()
                rule = ReorderRule(
                    sku=row["sku"].strip(),
                    reorder_point=parse_quantity(row["reorder_point"]),
                    reorder_qty=parse_quantity(row["reorder_qty"]),
                    max_level=parse_quantity(max_text) if max_text else None,
                )
            except (KeyError, ValueError) as exc:
                logger.warning("%s:%d: skipped rule row (%s)", path, line_no, exc)
                continue
            if rule.sku in rules:
                logger.warning("%s:%d: duplicate rule for %s replaces earlier one",
                               path, line_no, rule.sku)
            rules[rule.sku] = rule
    return rules
