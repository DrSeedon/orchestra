"""Settings of meterread, read from a file of ``key = value`` lines."""
from dataclasses import dataclass, fields
from decimal import Decimal

from meterread.money import parse_amount


@dataclass
class Settings:
    """Prices and display values. Prices are amounts with two places."""

    currency: str = "EUR"
    unit_price: Decimal = Decimal("0.28")
    standing_charge: Decimal = Decimal("0.45")


AMOUNT_KEYS = ("unit_price", "standing_charge")


def setting_names() -> list[str]:
    """List the names of all settings.

    :returns: the names, in the order of the ``Settings`` fields
    """
    return [field.name for field in fields(Settings)]


def load_settings(path: str | None) -> tuple[Settings | None, str | None]:
    """Read a settings file. Settings that the file does not name keep their defaults.

    :param path: the settings file, or None for the defaults only
    :returns: the settings and None, or None and an error message
    """
    settings = Settings()
    if path is None:
        return settings, None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as err:
        return None, f"cannot read {path}: {err.strerror}"
    names = setting_names()
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, text = line.partition("=")
        key, text = key.strip(), text.strip()
        if not sep or not text:
            return None, f"{path} line {number}: expected key = value"
        if key not in names:
            return None, f"{path} line {number}: unknown setting {key!r}"
        value = text
        if key in AMOUNT_KEYS:
            value, error = parse_amount(text)
            if error:
                return None, f"{path} line {number}: {error}"
        setattr(settings, key, value)
    return settings, None
