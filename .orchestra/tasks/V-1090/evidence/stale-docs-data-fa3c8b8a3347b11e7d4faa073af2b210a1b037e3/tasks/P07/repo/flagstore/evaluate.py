"""Flag evaluation with stable percentage rollouts."""
import hashlib
from datetime import datetime

from flagstore.flags import STATE_ON, STATE_ROLLOUT
from flagstore.store import FlagStore


def rollout_bucket(flag_name: str, user_id: str, salt: str) -> int:
    """Map a user to a stable bucket between 0 and 99 for one flag.

    Args:
        flag_name: Flag name.
        user_id: User identifier.
        salt: Value of the rollout_salt setting.

    Returns:
        The bucket number.
    """
    key = "{}:{}:{}".format(salt, flag_name, user_id).encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:8], 16) % 100


def is_enabled(
    store: FlagStore, name: str, user_id: str, now: datetime | None = None
) -> bool:
    """Decide whether a flag is on for a user and record the evaluation.

    Args:
        store: The flag store.
        name: Flag name.
        user_id: User identifier.
        now: Evaluation time in UTC. Defaults to the current time.

    Returns:
        True if the flag is on for this user. Unknown flags return the
        unknown_flag_default setting.
    """
    flag = store.get(name)
    if flag is None:
        return bool(store.settings["unknown_flag_default"])
    store.mark_evaluated(name, now)
    if flag.state == STATE_ON:
        return True
    if flag.state == STATE_ROLLOUT:
        salt = str(store.settings["rollout_salt"])
        return rollout_bucket(name, user_id, salt) < flag.rollout_percent
    return False


def enabled_flags(store: FlagStore, user_id: str, now: datetime | None = None) -> list[str]:
    """List the names of all flags that are on for a user.

    Args:
        store: The flag store.
        user_id: User identifier.
        now: Evaluation time in UTC. Defaults to the current time.

    Returns:
        Flag names, sorted.
    """
    return [flag.name for flag in store.all_flags() if is_enabled(store, flag.name, user_id, now)]
