"""Summaries of a single price list."""
from pricewatch.money import averageCents, formatCents
from pricewatch.pricelist import PriceItem


def cheapestItems(items: dict[str, PriceItem], count: int) -> list[PriceItem]:
    """Return the ``count`` cheapest items, cheapest first; equal prices go by sku."""
    if count < 1:
        raise ValueError("count must be at least 1, not {}".format(count))
    ranked = sorted(items.values(), key=lambda item: (item.price, item.sku))
    return ranked[:count]


def priceRange(items: dict[str, PriceItem]) -> tuple[int, int]:
    """Return the lowest and the highest price of ``items``, in cents."""
    if not items:
        raise ValueError("the price list is empty")
    prices = [item.price for item in items.values()]
    return min(prices), max(prices)


def formatItem(item: PriceItem) -> str:
    """Return one line for ``item``: sku, price and name."""
    return "{:<10} {:>9}  {}".format(item.sku, formatCents(item.price), item.name)


def summaryLines(items: dict[str, PriceItem]) -> list[str]:
    """Return the lines of the summary of a price list."""
    if not items:
        return ["items: 0"]
    lowCents, highCents = priceRange(items)
    averagePrice = averageCents([item.price for item in items.values()])
    return [
        "items: {}".format(len(items)),
        "lowest: {}".format(formatCents(lowCents)),
        "highest: {}".format(formatCents(highCents)),
        "average: {}".format(formatCents(averagePrice)),
    ]
