from notegrep.search import search, search_any

INDEX = {
    "tomato": ["garden", "kitchen"],
    "compost": ["garden", "old"],
    "soup": ["kitchen"],
}


def test_search_requires_all_words():
    assert search(INDEX, "tomato compost") == ["garden"]


def test_search_unknown_word():
    assert search(INDEX, "tomato pepper") == []


def test_search_empty_query():
    assert search(INDEX, "the and") == []


def test_search_any_ranks_by_hits():
    assert search_any(INDEX, "tomato soup compost") == [
        ("garden", 2),
        ("kitchen", 2),
        ("old", 1),
    ]
