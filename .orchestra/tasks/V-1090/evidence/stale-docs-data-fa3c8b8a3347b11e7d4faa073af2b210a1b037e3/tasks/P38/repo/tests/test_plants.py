import json
from datetime import date

import pytest

from plantcare.plants import Plant, load_plants, plant_from_dict, save_plants


def test_plant_from_dict_uses_default_interval():
    plant = plant_from_dict({"name": "Fern", "last_watered": "2026-07-01"}, 7)
    assert plant == Plant(name="Fern", interval=7, last_watered=date(2026, 7, 1))


def test_plant_needs_name():
    with pytest.raises(ValueError, match="needs a name"):
        plant_from_dict({"interval": 3}, 7)


@pytest.mark.parametrize("interval", [0, -2, "3", 1.5])
def test_plant_interval_must_be_whole_days(interval):
    with pytest.raises(ValueError, match="interval"):
        plant_from_dict({"name": "Fern", "interval": interval}, 7)


def test_missing_file_holds_no_plants(tmp_path):
    assert load_plants(tmp_path / "plants.json", 7) == []


def test_save_and_load_round_trip(tmp_path):
    plants = [
        Plant(name="Fern", interval=3, last_watered=date(2026, 7, 1), spot="bathroom"),
        Plant(name="Cactus", interval=14),
    ]
    path = tmp_path / "home" / "plants.json"
    save_plants(path, plants)
    assert load_plants(path, 7) == plants


def test_repeated_name(tmp_path):
    path = tmp_path / "plants.json"
    path.write_text(json.dumps({"plants": [{"name": "Fern"}, {"name": "Fern"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="appears twice"):
        load_plants(path, 7)
