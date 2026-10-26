"""Service settings: built-in defaults plus overrides from a JSON file."""
import json
import os

DEFAULT_SETTINGS: dict[str, object] = {
    "unknown_flag_default": False,
    "rollout_salt": "flagstore",
    "max_flags": 500,
}


def load_settings(file_name: str | None = None) -> dict[str, object]:
    """Load settings, applying overrides from a JSON file.

    Args:
        file_name: JSON file with setting overrides. When it is None or the
            file does not exist, only the defaults are used.

    Returns:
        A new dict that holds every known setting.

    Raises:
        ValueError: If the file names a setting that does not exist.
    """
    settings = dict(DEFAULT_SETTINGS)
    if file_name is None or not os.path.exists(file_name):
        return settings
    with open(file_name, encoding="utf-8") as handle:
        overrides = json.load(handle)
    unknown = sorted(set(overrides) - set(DEFAULT_SETTINGS))
    if unknown:
        raise ValueError("unknown settings: {}".format(", ".join(unknown)))
    settings.update(overrides)
    return settings


def describe_settings(settings: dict[str, object]) -> list[str]:
    """Return one "name = value" line per setting, sorted by name.

    Args:
        settings: Settings as returned by load_settings.

    Returns:
        The lines, suitable for a startup banner.
    """
    return ["{} = {!r}".format(name, settings[name]) for name in sorted(settings)]
