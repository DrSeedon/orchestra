"""Answer word queries against an index."""

from notegrep.parse import extract_words


def search(index: dict[str, list[str]], query: str) -> list[str]:
    """Return the notes that contain every word of ``query``.

    :param index: word to note names, as built by the index module.
    :param query: free text; it is split into words like note text.
    :returns: matching note names, sorted; empty if the query has no words.
    """
    words = extract_words(query)
    if not words:
        return []
    result: set[str] | None = None
    for word in words:
        names = set(index.get(word, []))
        result = names if result is None else result & names
        if not result:
            return []
    return sorted(result or [])


def search_any(index: dict[str, list[str]], query: str) -> list[tuple[str, int]]:
    """Rank notes by how many words of ``query`` they contain.

    :param index: word to note names.
    :param query: free text.
    :returns: pairs of note name and hit count, best first, then by name.
    """
    counts: dict[str, int] = {}
    for word in extract_words(query):
        for name in index.get(word, []):
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))
