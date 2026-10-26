import json

import pytest

from couponkit.errors import SettingsError
from couponkit.settings import DEFAULTS, load_settings


def write_settings(tmp_path, data):
    path = tmp_path / "shop.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_defaults_without_file():
    assert load_settings() == DEFAULTS


def test_file_overrides_defaults(tmp_path):
    settings = load_settings(write_settings(tmp_path, {"currency": "CHF"}))
    assert settings["currency"] == "CHF"
    assert settings["coupons_file"] == "coupons.json"


def test_unknown_setting(tmp_path):
    with pytest.raises(SettingsError, match="unknown setting"):
        load_settings(write_settings(tmp_path, {"colour": "green"}))


def test_wrong_type(tmp_path):
    with pytest.raises(SettingsError, match="currency must be of type str"):
        load_settings(write_settings(tmp_path, {"currency": 978}))


def test_not_an_object(tmp_path):
    with pytest.raises(SettingsError, match="JSON object"):
        load_settings(write_settings(tmp_path, ["currency"]))
