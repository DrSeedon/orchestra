import os

import pytest

from invoice_tool.suppliers import load_supplier_aliases, resolve_supplier, supplier_from_filename


def test_supplier_from_filename():
    assert supplier_from_filename("/data/in/ACME_2024-03.csv") == "acme"
    assert supplier_from_filename("globex-07.csv") == "globex"
    assert supplier_from_filename("initech.csv") == "initech"


def test_supplier_from_filename_rejects_bare_date():
    with pytest.raises(ValueError):
        supplier_from_filename("2024-03.csv")


def test_load_supplier_aliases(write_file):
    path = write_file("aliases.txt", "# known aliases\nacme-corp = acme\n\nGLOBEX INC = globex\n")
    assert load_supplier_aliases(path) == {"acme-corp": "acme", "globex inc": "globex"}


def test_load_supplier_aliases_missing_file_is_empty(tmp_path):
    assert load_supplier_aliases(os.path.join(str(tmp_path), "none.txt")) == {}


def test_load_supplier_aliases_bad_line(write_file):
    path = write_file("aliases.txt", "acme\n")
    with pytest.raises(ValueError, match="aliases.txt:1"):
        load_supplier_aliases(path)


def test_resolve_supplier_applies_alias():
    assert resolve_supplier("acmeco_2024-01.csv", {"acmeco": "acme"}) == "acme"
    assert resolve_supplier("globex.csv", {"acmeco": "acme"}) == "globex"
