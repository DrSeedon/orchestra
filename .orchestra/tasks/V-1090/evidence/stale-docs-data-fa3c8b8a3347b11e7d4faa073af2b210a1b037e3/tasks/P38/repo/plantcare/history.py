"""The watering history: one line per watering, ``YYYY-MM-DD name``."""
from datetime import date
from pathlib import Path


def append_history(path: Path, day: date, names: list[str]) -> None:
    """Add one line per plant in ``names`` to the history file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for name in names:
            handle.write(f"{day.isoformat()} {name}\n")


def read_history(path: Path) -> list[tuple[date, str]]:
    """Return the history as (day, plant name) pairs, in file order."""
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        day, _, name = line.partition(" ")
        try:
            entries.append((date.fromisoformat(day), name.strip()))
        except ValueError:
            raise ValueError(f"{path}, line {number}: bad date {day!r}") from None
    return entries
