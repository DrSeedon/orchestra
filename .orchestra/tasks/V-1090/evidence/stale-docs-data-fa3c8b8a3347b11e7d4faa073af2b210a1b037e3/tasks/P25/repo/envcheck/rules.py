"""Type checks for env values and the check of an env file against the schema."""
from urllib.parse import urlsplit

TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")


def is_int(value: str) -> bool:
    """Return True for a whole number with an optional sign, such as "8080" or "-1"."""
    text = value.strip()
    if text[:1] in ("+", "-"):
        text = text[1:]
    return text.isdigit()


def is_bool(value: str) -> bool:
    """Return True for one of TRUE_WORDS or FALSE_WORDS, in any case."""
    return value.strip().lower() in TRUE_WORDS + FALSE_WORDS


def is_url(value: str) -> bool:
    """Return True for a URL with a scheme and a host, such as "postgres://db/app"."""
    parts = urlsplit(value.strip())
    return bool(parts.scheme and parts.netloc)


def is_str(value: str) -> bool:
    """Return True: every value is a valid string."""
    return True


TYPE_CHECKS = {"int": is_int, "bool": is_bool, "url": is_url, "str": is_str}


def check_values(
    values: dict[str, str], schema: dict[str, dict], settings: dict[str, object]
) -> dict[str, list[str]]:
    """Check the values of an env file against the schema.

    A required variable that is not set is missing. An empty value counts as not
    set, unless the setting allow_empty is on. A value that fails the check of its
    type is invalid. Names that are not in the schema are not looked at.

    Args:
        values: The values of the env file by name.
        schema: The schema from load_schema.
        settings: The settings from load_settings.

    Returns:
        A dict with the keys "missing" and "invalid", each a sorted list of names.
    """
    missing = []
    invalid = []
    for name, spec in schema.items():
        value = values.get(name)
        if value is None or value == "":
            if spec["required"] and (value is None or not settings["allow_empty"]):
                missing.append(name)
            continue
        if not TYPE_CHECKS[spec["type"]](value):
            invalid.append(name)
    return {"missing": sorted(missing), "invalid": sorted(invalid)}
