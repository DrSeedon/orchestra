"""Settings of fuelcost: built-in defaults, updated from an optional JSON file."""
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

DEFAULTS: dict[str, Any] = {
    "price": Decimal("1.85"),
    "wear": Decimal("0.00"),
    "currency": "EUR",
}


def parseAmount(value: Any, name: str) -> Decimal:
    """Return a money amount from a JSON value; it must not be negative."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must not be negative, got {value!r}")
    return amount


def parsePrice(value: Any) -> Decimal:
    """Return the fuel price per litre; it must be above zero."""
    price = parseAmount(value, "price")
    if price == 0:
        raise ValueError("price must be above zero")
    return price


def parseWear(value: Any) -> Decimal:
    """Return the wear charge per km."""
    return parseAmount(value, "wear")


def parseCurrency(value: Any) -> str:
    """Return the currency code, for example EUR."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"currency must be a non-empty text, got {value!r}")
    return value.strip().upper()


PARSERS: dict[str, Callable[[Any], Any]] = {
    "price": parsePrice,
    "wear": parseWear,
    "currency": parseCurrency,
}


def loadSettings(path: str | None) -> dict[str, Any]:
    """Return the settings: the defaults, updated with the values of the JSON file at path.

    Raises OSError when the file cannot be read and ValueError when it is invalid.
    """
    settings = dict(DEFAULTS)
    if path is None:
        return settings
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    for key, value in data.items():
        parser = PARSERS.get(key)
        if parser is None:
            raise ValueError(f"{path}: unknown setting {key!r}")
        try:
            settings[key] = parser(value)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
    return settings
