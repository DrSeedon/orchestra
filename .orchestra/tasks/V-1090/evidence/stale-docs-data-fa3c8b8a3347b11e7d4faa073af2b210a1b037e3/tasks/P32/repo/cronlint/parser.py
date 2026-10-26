"""Parse cron expressions into schedules."""
from cronlint.errors import CronRangeError, CronSyntaxError
from cronlint.fields import BOUNDS, DAY, FIELD_ORDER, MACROS, WEEKDAY, name_value
from cronlint.schedule import Schedule


def parse_number(field: str, token: str) -> int:
    """Return the number that ``token`` stands for in ``field``."""
    value = name_value(field, token)
    if value is not None:
        return value
    if not token.isdigit():
        raise CronSyntaxError(f"{field}: {token!r} is not a number")
    return int(token)


def check_range(field: str, value: int) -> int:
    """Return ``value`` when ``field`` allows it."""
    low, high = BOUNDS[field]
    if field == WEEKDAY:
        high = 7
    if not low <= value <= high:
        raise CronRangeError(f"{field}: {value} is outside {low}-{high}")
    return value


def parse_part(field: str, part: str) -> set[int]:
    """Parse one comma-separated part: ``*``, ``a`` or ``a-b``, each with an
    optional ``/step``. ``a/step`` runs from ``a`` to the end of the range."""
    base, slash, step_text = part.partition("/")
    step = 1
    if slash:
        if not step_text.isdigit() or int(step_text) == 0:
            raise CronSyntaxError(f"{field}: bad step in {part!r}")
        step = int(step_text)
    low, high = BOUNDS[field]
    if base == "*":
        first, last = low, high
    elif "-" in base:
        start_text, _, end_text = base.partition("-")
        first = check_range(field, parse_number(field, start_text))
        last = check_range(field, parse_number(field, end_text))
        if first > last:
            raise CronRangeError(f"{field}: range {base!r} runs backwards")
    else:
        first = check_range(field, parse_number(field, base))
        last = high if slash else first
    return set(range(first, last + 1, step))


def parse_field(field: str, text: str) -> frozenset[int]:
    """Return the values that the field text ``text`` matches."""
    values = set()
    for part in text.split(","):
        if not part:
            raise CronSyntaxError(f"{field}: empty part in {text!r}")
        values |= parse_part(field, part)
    if field == WEEKDAY and 7 in values:
        values.discard(7)
        values.add(0)
    return frozenset(values)


def expand_macro(text: str) -> str:
    """Return the five-field form of a macro such as ``@daily``.

    Text that is not a macro comes back stripped but otherwise unchanged.
    """
    stripped = text.strip()
    if not stripped.startswith("@"):
        return stripped
    key = stripped.lower()
    if key not in MACROS:
        raise CronSyntaxError(f"unknown macro {stripped!r}")
    return MACROS[key]


def parse_expression(text: str) -> Schedule:
    """Parse a five-field cron expression or a macro into a ``Schedule``."""
    parts = expand_macro(text).split()
    if len(parts) != len(FIELD_ORDER):
        raise CronSyntaxError(f"expected {len(FIELD_ORDER)} fields, got {len(parts)}: {text!r}")
    values = {field: parse_field(field, part) for field, part in zip(FIELD_ORDER, parts)}
    day_text = parts[FIELD_ORDER.index(DAY)]
    weekday_text = parts[FIELD_ORDER.index(WEEKDAY)]
    return Schedule(text.strip(), values, day_star=day_text.startswith("*"),
                    weekday_star=weekday_text.startswith("*"))
