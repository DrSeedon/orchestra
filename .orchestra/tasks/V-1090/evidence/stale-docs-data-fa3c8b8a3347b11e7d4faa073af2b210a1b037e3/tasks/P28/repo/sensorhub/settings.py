"""Settings of sensorhub, read from the [sensorhub] section of an INI file."""
import configparser
from dataclasses import dataclass, fields

SECTION = "sensorhub"


@dataclass
class Settings:
    """Tunable values of sensorhub. All values are whole numbers; times are in minutes."""

    max_gap: int = 30
    decimals: int = 1
    min_readings: int = 3


def parse_setting(name: str, text: str) -> tuple[int | None, str | None]:
    """Turn the text of one setting into a whole number that is not negative."""
    try:
        value = int(text.strip())
    except ValueError:
        return None, f"setting {name} must be a whole number, got {text!r}"
    if value < 0:
        return None, f"setting {name} must not be negative, got {value}"
    return value, None


def load_settings(path: str | None) -> tuple[Settings | None, str | None]:
    """Read the settings file. With no path, or no [sensorhub] section, return the defaults.

    Settings that the file does not name keep their default values.
    """
    settings = Settings()
    if path is None:
        return settings, None
    parser = configparser.ConfigParser()
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as exc:
        return None, f"cannot read settings file {path}: {exc.strerror}"
    except configparser.Error as exc:
        return None, f"bad settings file {path}: {exc}"
    if not parser.has_section(SECTION):
        return settings, None
    known = {field.name for field in fields(Settings)}
    for name, text in parser.items(SECTION):
        if name not in known:
            return None, f"unknown setting {name!r} in {path}"
        value, error = parse_setting(name, text)
        if value is None:
            return None, error
        setattr(settings, name, value)
    return settings, None
