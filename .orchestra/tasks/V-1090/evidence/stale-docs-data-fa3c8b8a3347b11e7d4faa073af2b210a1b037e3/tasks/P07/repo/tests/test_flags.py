import pytest

from flagstore.flags import STATE_OFF, STATE_ROLLOUT, Flag, flag_to_dict, parse_flag


def test_parse_flag_with_defaults():
    flag = parse_flag({"name": "dark-mode", "state": STATE_OFF})
    assert flag == Flag("dark-mode", STATE_OFF, 0, "")


def test_round_trip():
    flag = Flag("checkout-v2", STATE_ROLLOUT, 25, "new checkout")
    assert parse_flag(flag_to_dict(flag)) == flag


def test_unknown_state():
    with pytest.raises(ValueError):
        parse_flag({"name": "x", "state": "maybe"})


def test_rollout_percent_range():
    with pytest.raises(ValueError):
        parse_flag({"name": "x", "state": STATE_ROLLOUT, "rollout_percent": 101})
