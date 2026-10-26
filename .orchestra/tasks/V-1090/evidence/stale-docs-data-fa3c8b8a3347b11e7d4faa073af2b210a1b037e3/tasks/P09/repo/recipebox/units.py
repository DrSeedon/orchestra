"""Unit conversion to base units: grams, millilitres and pieces."""

WEIGHT_TO_GRAMS: dict[str, float] = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
VOLUME_TO_ML: dict[str, float] = {
    "ml": 1.0,
    "l": 1000.0,
    "tsp": 4.92892,
    "tbsp": 14.7868,
    "cup": 236.588,
}
COUNT_UNITS: set[str] = {"", "pc", "pcs", "piece", "pieces"}

BASE_UNITS: dict[str, str] = {"weight": "g", "volume": "ml", "count": "pc"}


def unit_kind(unit: str) -> str:
    """Return "weight", "volume" or "count" for a unit symbol."""
    symbol = unit.strip().lower()
    if symbol in WEIGHT_TO_GRAMS:
        return "weight"
    if symbol in VOLUME_TO_ML:
        return "volume"
    if symbol in COUNT_UNITS:
        return "count"
    raise ValueError("unknown unit: {!r}".format(unit))


def to_base_unit(quantity: float, unit: str) -> tuple[float, str]:
    """Convert a quantity to the base unit of its kind, e.g. (1, "kg") -> (1000.0, "g")."""
    kind = unit_kind(unit)
    symbol = unit.strip().lower()
    if kind == "weight":
        return quantity * WEIGHT_TO_GRAMS[symbol], BASE_UNITS[kind]
    if kind == "volume":
        return quantity * VOLUME_TO_ML[symbol], BASE_UNITS[kind]
    return float(quantity), BASE_UNITS[kind]


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float:
    """Convert between two units of the same kind."""
    from_kind, to_kind = unit_kind(from_unit), unit_kind(to_unit)
    if from_kind != to_kind:
        raise ValueError("cannot convert {} to {}".format(from_unit, to_unit))
    base, _ = to_base_unit(quantity, from_unit)
    one_target, _ = to_base_unit(1.0, to_unit)
    return base / one_target
