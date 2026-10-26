from datetime import date

import pytest

from plantcare.plants import Plant
from plantcare.schedule import days_late, due_plants, next_watering, water

TODAY = date(2026, 7, 10)


@pytest.fixture
def plants():
    return [
        Plant(name="Fern", interval=3, last_watered=date(2026, 7, 8)),
        Plant(name="Basil", interval=1, last_watered=date(2026, 7, 7)),
        Plant(name="Cactus", interval=14, last_watered=date(2026, 6, 20)),
        Plant(name="Orchid", interval=5),
    ]


def test_next_watering(plants):
    assert next_watering(plants[0], TODAY) == date(2026, 7, 11)
    assert next_watering(plants[3], TODAY) == TODAY


def test_days_late(plants):
    assert days_late(plants[1], TODAY) == 2
    assert days_late(plants[0], TODAY) == 0


def test_due_plants_latest_first(plants):
    assert [plant.name for plant in due_plants(plants, TODAY)] == ["Cactus", "Basil", "Orchid"]


def test_water_marks_plants(plants):
    watered = water(plants, ["basil", "Orchid"], TODAY)
    assert [plant.name for plant in watered] == ["Basil", "Orchid"]
    assert plants[1].last_watered == TODAY
    assert plants[3].last_watered == TODAY


def test_water_unknown_plant(plants):
    with pytest.raises(KeyError, match="Rose"):
        water(plants, ["Fern", "Rose"], TODAY)
