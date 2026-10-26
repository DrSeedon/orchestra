import json

import pytest

from flagstore.settings import DEFAULT_SETTINGS, describe_settings, load_settings


def test_defaults_when_no_file():
    assert load_settings() == DEFAULT_SETTINGS
    assert load_settings() is not DEFAULT_SETTINGS


def test_missing_file_uses_defaults(tmp_path):
    assert load_settings(str(tmp_path / "nope.json")) == DEFAULT_SETTINGS


def test_overrides_from_file(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"max_flags": 3}), encoding="utf-8")
    settings = load_settings(str(settings_file))
    assert settings["max_flags"] == 3
    assert settings["rollout_salt"] == "flagstore"


def test_unknown_setting_is_rejected(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"colour": "blue"}), encoding="utf-8")
    with pytest.raises(ValueError, match="colour"):
        load_settings(str(settings_file))


def test_describe_settings():
    lines = describe_settings({"b": 1, "a": "x"})
    assert lines == ["a = 'x'", "b = 1"]
