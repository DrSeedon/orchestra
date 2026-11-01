"""When each plant needs water next."""
from datetime import date, timedelta

from plantcare.plants import Plant


def next_watering(plant: Plant, today: date) -> date:
    """Return the day ``plant`` needs water next; a plant never watered needs it today."""
    if plant.last_watered is None:
        return today
    return plant.last_watered + timedelta(days=plant.interval)


def days_late(plant: Plant, today: date) -> int:
    """Return how many days past its watering day ``plant`` is on ``today``."""
    return max(0, (today - next_watering(plant, today)).days)


def due_plants(plants: list[Plant], today: date) -> list[Plant]:
    """Return the plants that need water on ``today``, the latest first."""
    due = [plant for plant in plants if next_watering(plant, today) <= today]
    return sorted(due, key=lambda plant: -days_late(plant, today))


def water(plants: list[Plant], names: list[str], today: date) -> list[Plant]:
    """Mark the plants called ``names`` as watered on ``today`` and return them."""
    by_name = {plant.name.lower(): plant for plant in plants}
    unknown = [name for name in names if name.lower() not in by_name]
    if unknown:
        raise KeyError(f"unknown plant: {', '.join(unknown)}")
    watered = [by_name[name.lower()] for name in names]
    for plant in watered:
        plant.last_watered = today
    return watered
