from pathlib import Path

import pytest

from plantcare.settings import Settings, load_settings


def test_defaults_without_file():
    assert load_settings() == Settings()
    assert load_settings().plants_file == Path("plants.json")


def test_file_overrides_defaults(tmp_path):
    path = tmp_path / "plantcare.cfg"
    path.write_text("# home\nplants_file = home/plants.json\n\ndefault_interval = 4\n",
                    encoding="utf-8")
    settings = load_settings(path)
    assert settings.plants_file == Path("home/plants.json")
    assert settings.default_interval == 4
    assert settings.history_file is None


def test_unknown_setting(tmp_path):
    path = tmp_path / "plantcare.cfg"
    path.write_text("colour = green\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_settings(path)


def test_bad_value(tmp_path):
    path = tmp_path / "plantcare.cfg"
    path.write_text("default_interval = weekly\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad value for default_interval"):
        load_settings(path)


def test_interval_must_be_positive(tmp_path):
    path = tmp_path / "plantcare.cfg"
    path.write_text("default_interval = 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at least 1"):
        load_settings(path)
