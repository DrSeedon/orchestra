import pytest

from cartkit.catalog import load_catalog
from cartkit.errors import InvalidPriceError, UnknownProductError


def test_load_catalog_reads_rows(catalog):
    assert len(catalog) == 3
    assert catalog.skus() == ["KET-03", "MUG-01", "TEA-02"]
    mug = catalog.get("MUG-01")
    assert mug.name == "Coffee mug"
    assert mug.unit_price_cents == 1250
    assert mug.weight_grams == 400


def test_unknown_sku(catalog):
    with pytest.raises(UnknownProductError):
        catalog.get("NOPE")


def test_bad_price_reports_row():
    text = "sku,name,price,weight_grams\nA,Thing,1.00,10\nB,Other,lots,10\n"
    with pytest.raises(InvalidPriceError, match="row 3"):
        load_catalog(text)
