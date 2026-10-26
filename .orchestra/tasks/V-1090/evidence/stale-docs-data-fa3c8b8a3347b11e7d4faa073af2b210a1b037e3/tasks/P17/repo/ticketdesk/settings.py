"""Desk settings: SLA hours per priority and the time format of the export.

Settings come from an optional JSON file. Keys that are left out keep their
default value. Unknown keys, values of the wrong type and hour values that are
not positive make the file invalid.
"""

import json

DEFAULT_SETTINGS: dict[str, object] = {
    "urgent_hours": 4,
    "high_hours": 24,
    "normal_hours": 72,
    "low_hours": 168,
    "time_format": "%Y-%m-%d %H:%M",
}


def check_value(key: str, value: object) -> str | None:
    """Return an error message when value is not valid for key, else None."""
    if key not in DEFAULT_SETTINGS:
        return f"unknown setting {key!r}"
    expected = type(DEFAULT_SETTINGS[key])
    if type(value) is not expected:
        return f"setting {key!r} must be of type {expected.__name__}"
    if key.endswith("_hours") and value <= 0:
        return f"setting {key!r} must be greater than 0"
    return None


def load_settings(path: str | None = None) -> tuple[dict[str, object] | None, str | None]:
    """Return (settings, None), or (None, message) when the file cannot be used."""
    settings = dict(DEFAULT_SETTINGS)
    if path is None:
        return settings, None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as err:
        return None, f"cannot read settings file {path}: {err.strerror}"
    except json.JSONDecodeError as err:
        return None, f"{path}: not valid JSON ({err.msg})"
    if not isinstance(data, dict):
        return None, f"{path}: expected a JSON object"
    for key, value in data.items():
        error = check_value(key, value)
        if error is not None:
            return None, f"{path}: {error}"
        settings[key] = value
    return settings, None
