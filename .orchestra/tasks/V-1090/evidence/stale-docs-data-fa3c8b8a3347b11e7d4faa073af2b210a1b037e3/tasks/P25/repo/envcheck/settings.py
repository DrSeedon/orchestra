"""Read the settings file: an INI file with one [envcheck] section."""
import configparser
import os

from envcheck.errors import SettingsError

SECTION = "envcheck"

DEFAULTS: dict[str, object] = {
    "schema": "env.schema",
    "allow_empty": False,
}


def load_settings(path: str) -> dict[str, object]:
    """Read the settings file.

    Keys that the file does not set keep their value from DEFAULTS. Keys with a
    True or False default take yes/no, true/false or on/off.

    Args:
        path: Path of the settings file.

    Returns:
        The settings by key. "schema" is an absolute path, found from the folder
        of the settings file.

    Raises:
        SettingsError: The file cannot be read, has no [envcheck] section, sets
            an unknown key or has a bad yes/no value.
    """
    base = os.path.basename(path)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as error:
        raise SettingsError(f"cannot read {path}: {error.strerror}") from None
    except configparser.Error as error:
        raise SettingsError(f"{base}: {error}") from None
    if not parser.has_section(SECTION):
        raise SettingsError(f"{base}: no [{SECTION}] section")
    section = parser[SECTION]
    settings = dict(DEFAULTS)
    for key in section:
        if key not in DEFAULTS:
            raise SettingsError(f"{base}: unknown setting {key!r}")
        if isinstance(DEFAULTS[key], bool):
            try:
                settings[key] = section.getboolean(key)
            except ValueError:
                raise SettingsError(f"{base}: {key} must be yes or no") from None
        else:
            settings[key] = section[key].strip()
    folder = os.path.dirname(os.path.abspath(path))
    settings["schema"] = os.path.join(folder, str(settings["schema"]))
    return settings
