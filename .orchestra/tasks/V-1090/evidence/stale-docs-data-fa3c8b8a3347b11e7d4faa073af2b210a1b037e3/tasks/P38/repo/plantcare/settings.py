"""Settings: built-in defaults that a settings file can override.

A settings file has one ``key = value`` line per setting. Blank lines and
lines that start with ``#`` are skipped.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class Settings:
    """All settings of plantcare, with their defaults."""

    plants_file: Path = Path("plants.json")
    default_interval: int = 7
    history_file: Optional[Path] = None


_CONVERTERS: dict[str, Callable[[str], object]] = {
    "plants_file": Path,
    "default_interval": int,
    "history_file": Path,
}


def load_settings(path: Optional[Path] = None) -> Settings:
    """Return the settings, with the values of the file at ``path`` when one is given."""
    settings = Settings()
    if path is None:
        return settings
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = (part.strip() for part in line.partition("="))
        if not sep or key not in _CONVERTERS:
            raise ValueError(f"{path}, line {number}: expected a known setting as key = value")
        try:
            setattr(settings, key, _CONVERTERS[key](value))
        except ValueError:
            raise ValueError(f"{path}, line {number}: bad value for {key}: {value!r}") from None
    if settings.default_interval < 1:
        raise ValueError(f"default_interval must be at least 1, not {settings.default_interval}")
    return settings
