from datetime import datetime, timezone

from flagstore.evaluate import enabled_flags, is_enabled, rollout_bucket
from flagstore.flags import STATE_OFF, STATE_ON, STATE_ROLLOUT, Flag
from flagstore.settings import load_settings
from flagstore.store import FlagStore

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_store():
    store = FlagStore(load_settings())
    store.put(Flag("on", STATE_ON))
    store.put(Flag("off", STATE_OFF))
    store.put(Flag("half", STATE_ROLLOUT, 50))
    return store


def test_bucket_is_stable_and_in_range():
    first = rollout_bucket("half", "user-1", "salt")
    assert first == rollout_bucket("half", "user-1", "salt")
    assert 0 <= first < 100


def test_on_and_off():
    store = make_store()
    assert is_enabled(store, "on", "u", NOW) is True
    assert is_enabled(store, "off", "u", NOW) is False


def test_rollout_splits_users():
    store = make_store()
    results = [is_enabled(store, "half", "user-{}".format(i), NOW) for i in range(200)]
    assert 60 < sum(results) < 140


def test_unknown_flag_uses_setting():
    store = make_store()
    assert is_enabled(store, "missing", "u") is False
    store.settings["unknown_flag_default"] = True
    assert is_enabled(store, "missing", "u") is True


def test_evaluation_is_recorded():
    store = make_store()
    is_enabled(store, "off", "u", NOW)
    assert store.last_evaluated("off") == NOW
    assert store.last_evaluated("on") is None


def test_enabled_flags():
    store = make_store()
    names = enabled_flags(store, "u", NOW)
    assert "on" in names
    assert "off" not in names
