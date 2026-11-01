import pytest

from csvmerge.columns import describe_columns, normalize_header, normalize_name, same_columns
from csvmerge.errors import ColumnError


def test_normalize_name():
    assert normalize_name("  Unit Price ") == "unit_price"
    assert normalize_name("SKU") == "sku"
    assert normalize_name("in  stock") == "in_stock"


def test_normalize_header():
    assert normalize_header(["SKU", " Name", "Unit price"]) == ["sku", "name", "unit_price"]


def test_blank_column_name_is_rejected():
    with pytest.raises(ColumnError, match="column 2"):
        normalize_header(["sku", "  ", "name"])


def test_repeated_column_name_is_rejected():
    with pytest.raises(ColumnError, match="'name'"):
        normalize_header(["sku", "Name", "name "])


def test_same_columns_ignores_order():
    assert same_columns(["a", "b"], ["b", "a"])
    assert not same_columns(["a", "b"], ["a", "c"])


def test_describe_columns():
    assert describe_columns(["a", "b"]) == "a, b"
    assert describe_columns([]) == "(none)"
