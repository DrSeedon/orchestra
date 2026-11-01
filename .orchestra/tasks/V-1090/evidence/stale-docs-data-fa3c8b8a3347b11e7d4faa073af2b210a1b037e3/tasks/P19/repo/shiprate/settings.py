"""Settings of the rate calculation and the loader for the settings file."""

import json
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Settings:
    """Settings of the rate calculation.

    Attributes:
        currency: currency code of all amounts.
        fuel_percent: fuel surcharge in percent of the base rate.
        max_weight_grams: heaviest parcel that is accepted.
    """

    currency: str = "EUR"
    fuel_percent: int = 8
    max_weight_grams: int = 31500


def load_settings(path: str | None = None) -> Settings:
    """Load the settings, with the values of a JSON file over the defaults.

    Args:
        path: JSON file with an object of settings, or None for the defaults.

    Returns:
        The settings; keys that the file leaves out keep their defaults.

    Raises:
        ValueError: if a key is unknown or a value has the wrong type or sign.
    """
    settings = Settings()
    if path is None:
        return settings
    with open(path, encoding="utf-8") as handle:
        values = json.load(handle)
    if not isinstance(values, dict):
        raise ValueError(f"{path}: the settings must be a JSON object")
    defaults = {item.name: getattr(settings, item.name) for item in fields(Settings)}
    for key, value in values.items():
        if key not in defaults:
            raise ValueError(f"{path}: unknown setting {key!r}")
        expected = type(defaults[key])
        if type(value) is not expected:
            raise ValueError(f"{path}: {key} must be of type {expected.__name__}")
        if expected is int and value < 0:
            raise ValueError(f"{path}: {key} must not be negative")
    return replace(settings, **values)
