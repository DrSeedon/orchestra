"""In-memory stock levels per SKU and location."""
import logging

from stockroom.models import StockLevel

logger = logging.getLogger(__name__)


class Inventory:
    """Holds one StockLevel per (sku, location) pair."""

    def __init__(self, levels: list[StockLevel] | None = None) -> None:
        self._levels: dict[tuple[str, str], StockLevel] = {}
        for level in levels or []:
            self._levels[(level.sku, level.location)] = level

    def get_level(self, sku: str, location: str) -> StockLevel:
        """Return the level for a SKU at a location, creating an empty one if needed."""
        key = (sku, location)
        if key not in self._levels:
            self._levels[key] = StockLevel(sku=sku, location=location, on_hand=0)
        return self._levels[key]

    def add_stock(self, sku: str, location: str, quantity: int) -> int:
        """Receive stock and return the new on-hand quantity."""
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        level = self.get_level(sku, location)
        level.on_hand += quantity
        logger.info("received %d of %s at %s", quantity, sku, location)
        return level.on_hand

    def remove_stock(self, sku: str, location: str, quantity: int) -> int:
        """Ship or consume stock and return the new on-hand quantity."""
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        level = self.get_level(sku, location)
        if quantity > level.available:
            logger.warning(
                "cannot remove %d of %s at %s: only %d available",
                quantity, sku, location, level.available,
            )
            raise ValueError(f"insufficient stock for {sku} at {location}")
        level.on_hand -= quantity
        return level.on_hand

    def reserve(self, sku: str, location: str, quantity: int) -> None:
        """Hold stock for an open order so it no longer counts as available."""
        level = self.get_level(sku, location)
        if quantity > level.available:
            raise ValueError(f"cannot reserve {quantity} of {sku} at {location}")
        level.reserved += quantity

    def locations(self) -> set[str]:
        return {location for _, location in self._levels}

    def levels_at(self, location: str) -> list[StockLevel]:
        """Return all levels at one location, sorted by SKU."""
        found = [level for level in self._levels.values() if level.location == location]
        return sorted(found, key=lambda level: level.sku)

    def total_on_hand(self, sku: str) -> int:
        return sum(level.on_hand for level in self._levels.values() if level.sku == sku)
