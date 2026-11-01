from decimal import Decimal

import pytest

from tipjar.split import split_evenly


def test_split_evenly_gives_leftover_to_the_first_people():
    shares = split_evenly(Decimal("10.00"), 3)
    assert shares == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert sum(shares) == Decimal("10.00")


def test_split_evenly_with_one_person():
    assert split_evenly(Decimal("62.68"), 1) == [Decimal("62.68")]


def test_split_evenly_needs_people():
    with pytest.raises(ValueError):
        split_evenly(Decimal("10.00"), 0)
