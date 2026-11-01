from datetime import datetime, timezone

import pytest

from flagstore.flags import STATE_OFF, STATE_ON, Flag
from flagstore.settings import load_settings
from flagstore.store import FlagStore, load_flags, save_flags


def make_store(**overrides):
    settings = load_settings()
    settings.update(overrides)
    return FlagStore(settings)


def test_put_get_remove():
    store = make_store()
    store.put(Flag("a", STATE_ON))
    assert store.get("a") == Flag("a", STATE_ON)
    assert store.get("b") is None
    assert store.remove("a") is True
    assert store.remove("a") is False


def test_max_flags():
    store = make_store(max_flags=1)
    store.put(Flag("a", STATE_ON))
    store.put(Flag("a", STATE_OFF))
    with pytest.raises(ValueError):
        store.put(Flag("b", STATE_ON))


def test_evaluation_times():
    store = make_store()
    when = datetime(2024, 5, 1, tzinfo=timezone.utc)
    assert store.last_evaluated("a") is None
    store.mark_evaluated("a", when)
    assert store.last_evaluated("a") == when


def test_save_and_load(tmp_path):
    store = make_store()
    store.put(Flag("b", STATE_OFF, 0, "second"))
    store.put(Flag("a", STATE_ON))
    flags_file = str(tmp_path / "flags.json")
    save_flags(store, flags_file)
    other = make_store()
    assert load_flags(other, flags_file) == 2
    assert other.all_flags() == store.all_flags()
