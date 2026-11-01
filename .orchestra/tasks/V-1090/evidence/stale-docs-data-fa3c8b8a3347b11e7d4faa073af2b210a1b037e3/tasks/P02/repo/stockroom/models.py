"""Record types shared by the stockroom modules."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    unit: str = "each"


@dataclass
class StockLevel:
    sku: str
    location: str
    on_hand: int
    reserved: int = 0

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass(frozen=True)
class ReorderRule:
    sku: str
    reorder_point: int
    reorder_qty: int
    max_level: int | None = None


@dataclass(frozen=True)
class OrderLine:
    sku: str
    location: str
    quantity: int
