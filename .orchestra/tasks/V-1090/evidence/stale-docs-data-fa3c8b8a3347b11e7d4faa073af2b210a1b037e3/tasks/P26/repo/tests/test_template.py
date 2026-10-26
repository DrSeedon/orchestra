import pytest

from mailmerge.template import field_value, load_template, render, template_fields

TEXT = "Hi {{name}},\nyour order {{ order }} ships to {{city}}. Thanks, {{name}}!\n"


def test_load_template(write_file):
    assert load_template(write_file("t.txt", TEXT)) == TEXT


def test_load_template_rejects_empty_file(write_file):
    with pytest.raises(ValueError, match="template is empty"):
        load_template(write_file("t.txt", "  \n"))


def test_template_fields_in_order_of_first_use():
    assert template_fields(TEXT) == ["name", "order", "city"]


def test_field_value_uses_defaults():
    assert field_value("city", {"city": " Oslo "}) == "Oslo"
    assert field_value("city", {"city": ""}, {"city": "Rome"}) == "Rome"
    with pytest.raises(ValueError, match="no value for field 'city'"):
        field_value("city", {}, {"name": "x"})


def test_render():
    values = {"name": "Ann", "order": "A-1", "city": "Oslo"}
    assert render(TEXT, values) == "Hi Ann,\nyour order A-1 ships to Oslo. Thanks, Ann!\n"


def test_render_missing_value():
    with pytest.raises(ValueError):
        render(TEXT, {"name": "Ann", "order": "A-1"})
