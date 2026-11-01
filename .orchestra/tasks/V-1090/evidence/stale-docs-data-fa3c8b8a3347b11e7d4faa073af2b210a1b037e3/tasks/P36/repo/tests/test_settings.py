import json

import pytest

from kanbanlite.settings import DEFAULTS, load_settings


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_defaults_without_file():
    assert load_settings() == DEFAULTS


def test_file_values_override_defaults(tmp_path):
    path = write_json(tmp_path / "kanban.json", {"board_file": "team.json", "max_title_length": 40})
    settings = load_settings(path)
    assert settings["board_file"] == "team.json"
    assert settings["max_title_length"] == 40
    assert settings["default_priority"] == "normal"


def test_unknown_key_is_an_error(tmp_path):
    path = write_json(tmp_path / "kanban.json", {"colour": "blue"})
    with pytest.raises(ValueError, match="unknown settings: colour"):
        load_settings(path)


@pytest.mark.parametrize("value", [0, -3, "80", True])
def test_bad_title_length(tmp_path, value):
    path = write_json(tmp_path / "kanban.json", {"max_title_length": value})
    with pytest.raises(ValueError, match="max_title_length"):
        load_settings(path)


def test_bad_default_priority(tmp_path):
    path = write_json(tmp_path / "kanban.json", {"default_priority": "asap"})
    with pytest.raises(ValueError, match="unknown priority"):
        load_settings(path)


def test_settings_must_be_an_object(tmp_path):
    path = write_json(tmp_path / "kanban.json", ["board.json"])
    with pytest.raises(ValueError, match="JSON object"):
        load_settings(path)
