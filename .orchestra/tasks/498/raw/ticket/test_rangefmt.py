from rangefmt import humanize_ranges


def test_empty():
    assert humanize_ranges([]) == ""


def test_single():
    assert humanize_ranges([7]) == "7"


def test_simple_run():
    assert humanize_ranges([1, 2, 3]) == "1-3"


def test_mixed():
    assert humanize_ranges([1, 2, 3, 5, 7, 8, 9]) == "1-3,5,7-9"


def test_pair_is_not_collapsed():
    assert humanize_ranges([1, 2, 5]) == "1,2,5"


def test_unsorted_input():
    assert humanize_ranges([9, 7, 8, 3, 1, 2]) == "1-3,7-9"


def test_duplicates():
    assert humanize_ranges([1, 1, 2, 3, 3]) == "1-3"


def test_negatives():
    assert humanize_ranges([-3, -2, -1, 4, 5]) == "-3--1,4,5"
