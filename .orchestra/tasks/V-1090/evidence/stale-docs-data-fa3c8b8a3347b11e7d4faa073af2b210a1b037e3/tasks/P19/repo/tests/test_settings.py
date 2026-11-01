import json

import pytest

from shiprate.settings import Settings, load_settings


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def test_defaults():
    settings = load_settings()
    assert settings == Settings()
    assert settings.currency == "EUR"
    assert settings.fuel_percent == 8
    assert settings.max_weight_grams == 31500


def test_file_overrides_some_keys(tmp_path):
    settings = load_settings(write_json(tmp_path / "s.json", {"fuel_percent": 12, "currency": "CHF"}))
    assert settings.fuel_percent == 12
    assert settings.currency == "CHF"
    assert settings.max_weight_grams == 31500


@pytest.mark.parametrize("values, message", [
    ({"fuel": 3}, "unknown setting"),
    ({"fuel_percent": "8"}, "must be of type int"),
    ({"fuel_percent": 8.5}, "must be of type int"),
    ({"fuel_percent": True}, "must be of type int"),
    ({"max_weight_grams": -1}, "must not be negative"),
])
def test_invalid_settings(tmp_path, values, message):
    with pytest.raises(ValueError, match=message):
        load_settings(write_json(tmp_path / "s.json", values))


def test_settings_must_be_an_object(tmp_path):
    with pytest.raises(ValueError, match="JSON object"):
        load_settings(write_json(tmp_path / "s.json", [1, 2]))
