"""Flag records and conversion from and to plain dicts."""
from typing import NamedTuple

STATE_ON = "on"
STATE_OFF = "off"
STATE_ROLLOUT = "rollout"
VALID_STATES = (STATE_ON, STATE_OFF, STATE_ROLLOUT)


class Flag(NamedTuple):
    """A feature flag definition."""

    name: str
    state: str
    rollout_percent: int = 0
    description: str = ""


def parse_flag(data: dict[str, object]) -> Flag:
    """Build a flag from a dict as stored in the flags file.

    Args:
        data: Mapping with "name" and "state", and optionally
            "rollout_percent" and "description".

    Returns:
        The parsed flag.

    Raises:
        ValueError: If the state is unknown or the rollout percent is not 0-100.
    """
    state = str(data["state"])
    if state not in VALID_STATES:
        raise ValueError("unknown flag state: {}".format(state))
    percent = int(data.get("rollout_percent", 0))
    if not 0 <= percent <= 100:
        raise ValueError("rollout percent out of range: {}".format(percent))
    return Flag(
        name=str(data["name"]),
        state=state,
        rollout_percent=percent,
        description=str(data.get("description", "")),
    )


def flag_to_dict(flag: Flag) -> dict[str, object]:
    """Convert a flag to a dict that parse_flag can read back.

    Args:
        flag: The flag to convert.

    Returns:
        A JSON-serialisable dict.
    """
    return {
        "name": flag.name,
        "state": flag.state,
        "rollout_percent": flag.rollout_percent,
        "description": flag.description,
    }
