"""The plant file: which plants we have and how often they need water."""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass
class Plant:
    """One plant. ``interval`` is the number of days between two waterings."""

    name: str
    interval: int
    last_watered: Optional[date] = None
    spot: Optional[str] = None


def plant_from_dict(data: dict, default_interval: int) -> Plant:
    """Build a plant from one entry of the plant file."""
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("every plant needs a name")
    interval = data.get("interval", default_interval)
    if not isinstance(interval, int) or interval < 1:
        raise ValueError(f"{name}: interval must be a whole number of days, at least 1")
    last = data.get("last_watered")
    return Plant(
        name=name,
        interval=interval,
        last_watered=date.fromisoformat(last) if last else None,
        spot=data.get("spot") or None,
    )


def plant_to_dict(plant: Plant) -> dict:
    """Return the plant file entry of ``plant``."""
    data = {"name": plant.name, "interval": plant.interval}
    if plant.last_watered is not None:
        data["last_watered"] = plant.last_watered.isoformat()
    if plant.spot:
        data["spot"] = plant.spot
    return data


def load_plants(path: Path, default_interval: int) -> list[Plant]:
    """Read the plant file; a file that does not exist holds no plants."""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    plants = [plant_from_dict(entry, default_interval) for entry in data.get("plants", [])]
    seen: set[str] = set()
    for plant in plants:
        if plant.name in seen:
            raise ValueError(f"{path}: plant {plant.name!r} appears twice")
        seen.add(plant.name)
    return plants


def save_plants(path: Path, plants: list[Plant]) -> None:
    """Write ``plants`` to the plant file at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"plants": [plant_to_dict(plant) for plant in plants]}, indent=2)
    path.write_text(text + "\n", encoding="utf-8")
