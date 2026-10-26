import os

import pytest

from envcheck.errors import SettingsError
from envcheck.settings import load_settings


def write(tmp_path, text):
    path = tmp_path / "envcheck.ini"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_settings_uses_defaults(tmp_path):
    settings = load_settings(write(tmp_path, "[envcheck]\n"))
    assert settings["allow_empty"] is False
    assert settings["schema"] == os.path.join(str(tmp_path), "env.schema")


def test_load_settings_reads_values(tmp_path):
    settings = load_settings(write(tmp_path, "[envcheck]\nschema = conf/app.schema\nallow_empty = yes\n"))
    assert settings["allow_empty"] is True
    assert settings["schema"] == os.path.join(str(tmp_path), "conf/app.schema")


@pytest.mark.parametrize(
    "text",
    ["[other]\n", "[envcheck]\ncolour = red\n", "[envcheck]\nallow_empty = sometimes\n", "not ini\n"],
)
def test_load_settings_rejects_bad_files(tmp_path, text):
    with pytest.raises(SettingsError):
        load_settings(write(tmp_path, text))


def test_load_settings_needs_the_file(tmp_path):
    with pytest.raises(SettingsError):
        load_settings(str(tmp_path / "missing.ini"))
