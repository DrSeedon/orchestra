"""Settings: built-in defaults that a JSON settings file can override."""
import json
from typing import Optional

from couponkit.errors import SettingsError

DEFAULTS: dict[str, object] = {
    "coupons_file": "coupons.json",
    "currency": "EUR",
}


def load_settings(path: Optional[str] = None) -> dict[str, object]:
    """Return the settings: the defaults, with the values of the file at ``path``."""
    settings = dict(DEFAULTS)
    if path is None:
        return settings
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as error:
            raise SettingsError(f"{path}: not valid JSON ({error.msg})") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a JSON object")
    for key, value in data.items():
        if key not in DEFAULTS:
            raise SettingsError(f"{path}: unknown setting {key!r}")
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise SettingsError(f"{path}: {key} must be of type {expected.__name__}")
        settings[key] = value
    return settings
