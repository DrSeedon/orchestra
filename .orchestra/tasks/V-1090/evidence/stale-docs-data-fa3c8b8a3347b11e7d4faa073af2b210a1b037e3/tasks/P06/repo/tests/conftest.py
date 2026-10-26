import pytest

from cartkit.catalog import load_catalog

CATALOG_CSV = """sku,name,price,weight_grams
MUG-01,Coffee mug,12.50,400
TEA-02,Green tea,4.99,120
KET-03,Kettle,39.00,1300
"""


@pytest.fixture
def catalog():
    return load_catalog(CATALOG_CSV)
