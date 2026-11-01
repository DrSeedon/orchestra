"""In-memory flag store that also records when each flag was last evaluated."""
import json
from datetime import datetime, timezone

from flagstore.flags import Flag, flag_to_dict, parse_flag


class FlagStore:
    """Holds flag definitions by name, plus their last evaluation times."""

    def __init__(self, settings: dict[str, object]) -> None:
        """Create an empty store.

        Args:
            settings: Settings as returned by load_settings.
        """
        self.settings = settings
        self._flags: dict[str, Flag] = {}
        self._last_evaluated: dict[str, datetime] = {}

    def put(self, flag: Flag) -> None:
        """Add a flag or replace the flag with the same name.

        Args:
            flag: The flag to store.

        Raises:
            ValueError: If adding a new flag would exceed the max_flags setting.
        """
        limit = int(self.settings["max_flags"])
        if flag.name not in self._flags and len(self._flags) >= limit:
            raise ValueError("store is full ({} flags)".format(limit))
        self._flags[flag.name] = flag

    def get(self, name: str) -> Flag | None:
        """Look up a flag.

        Args:
            name: Flag name.

        Returns:
            The flag, or None if no flag has that name.
        """
        return self._flags.get(name)

    def remove(self, name: str) -> bool:
        """Delete a flag and its evaluation history.

        Args:
            name: Flag name.

        Returns:
            True if a flag was removed, False if it did not exist.
        """
        self._last_evaluated.pop(name, None)
        return self._flags.pop(name, None) is not None

    def all_flags(self) -> list[Flag]:
        """Return every flag, sorted by name.

        Returns:
            The flags.
        """
        return [self._flags[name] for name in sorted(self._flags)]

    def mark_evaluated(self, name: str, when: datetime | None = None) -> None:
        """Record that a flag was evaluated.

        Args:
            name: Flag name.
            when: Evaluation time in UTC. Defaults to the current time.
        """
        self._last_evaluated[name] = when or datetime.now(timezone.utc)

    def last_evaluated(self, name: str) -> datetime | None:
        """Return when a flag was last evaluated.

        Args:
            name: Flag name.

        Returns:
            The time of the last evaluation, or None if it was never evaluated.
        """
        return self._last_evaluated.get(name)


def load_flags(store: FlagStore, file_name: str) -> int:
    """Load flag definitions from a JSON list into a store.

    Args:
        store: The store to fill.
        file_name: JSON file holding a list of flag dicts.

    Returns:
        The number of flags loaded.
    """
    with open(file_name, encoding="utf-8") as handle:
        items = json.load(handle)
    for item in items:
        store.put(parse_flag(item))
    return len(items)


def save_flags(store: FlagStore, file_name: str) -> None:
    """Write every flag in a store to a JSON file.

    Args:
        store: The store to save.
        file_name: Target file; it is overwritten.
    """
    with open(file_name, "w", encoding="utf-8") as handle:
        json.dump([flag_to_dict(flag) for flag in store.all_flags()], handle, indent=2)
