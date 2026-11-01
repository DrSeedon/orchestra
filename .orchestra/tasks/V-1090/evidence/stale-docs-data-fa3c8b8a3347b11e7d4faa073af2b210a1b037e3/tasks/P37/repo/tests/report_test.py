import pytest

from pricewatch.pricelist import PriceItem
from pricewatch.report import cheapestItems, formatItem, priceRange, summaryLines


@pytest.fixture
def items():
    return {
        "A-1": PriceItem(sku="A-1", name="Desk lamp", price=2000),
        "B-2": PriceItem(sku="B-2", name="Stapler", price=825),
        "B-3": PriceItem(sku="B-3", name="Paper ream", price=480),
        "C-9": PriceItem(sku="C-9", name="Pencil case", price=825),
    }


def test_cheapest_items(items):
    assert [item.sku for item in cheapestItems(items, 3)] == ["B-3", "B-2", "C-9"]


def test_cheapest_needs_positive_count(items):
    with pytest.raises(ValueError, match="at least 1"):
        cheapestItems(items, 0)


def test_price_range(items):
    assert priceRange(items) == (480, 2000)


def test_format_item(items):
    assert formatItem(items["B-2"]) == "B-2             8.25  Stapler"


def test_summary_lines(items):
    assert summaryLines(items) == [
        "items: 4",
        "lowest: 4.80",
        "highest: 20.00",
        "average: 10.33",
    ]


def test_summary_of_empty_list():
    assert summaryLines({}) == ["items: 0"]
