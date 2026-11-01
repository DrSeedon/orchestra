"""Load the board settings from a JSON file and fill in defaults."""
import json

from kanbanlite.model import parse_priority

DEFAULTS = {
    "board_file": "board.json",
    "default_priority": "normal",
    "max_title_length": 80,
}


def load_settings(path: str | None = None) -> dict:
    """Return the settings of ``path`` merged over the defaults.

    Without a path the defaults are returned. Unknown keys are an error.
    """
    settings = dict(DEFAULTS)
    if path is None:
        return settings
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: settings must be a JSON object")
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"{path}: unknown settings: {', '.join(unknown)}")
    settings.update(data)
    length = settings["max_title_length"]
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError(f"{path}: max_title_length must be a whole number of at least 1")
    parse_priority(settings["default_priority"])
    return settings
