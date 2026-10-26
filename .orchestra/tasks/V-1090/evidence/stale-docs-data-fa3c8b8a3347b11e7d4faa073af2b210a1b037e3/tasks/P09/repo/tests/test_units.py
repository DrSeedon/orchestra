import pytest

from recipebox.units import convert_quantity, to_base_unit, unit_kind


def test_unit_kind():
    assert unit_kind("kg") == "weight"
    assert unit_kind("Tbsp") == "volume"
    assert unit_kind("pieces") == "count"
    with pytest.raises(ValueError):
        unit_kind("handful")


def test_to_base_unit():
    assert to_base_unit(1.5, "kg") == (1500.0, "g")
    assert to_base_unit(2, "l") == (2000.0, "ml")
    assert to_base_unit(3, "pc") == (3.0, "pc")


def test_convert_quantity():
    assert convert_quantity(2, "cup", "ml") == pytest.approx(473.176)
    assert convert_quantity(1000, "g", "kg") == pytest.approx(1.0)
    with pytest.raises(ValueError):
        convert_quantity(1, "g", "ml")
