"""Pull titles, words and links out of markdown text."""

import re

WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
LINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
STOP_WORDS = frozenset({"a", "an", "and", "the", "of", "to", "in", "is", "it", "on", "for"})


def extract_title(text: str) -> str:
    """Return the text of the first level-one heading.

    :param text: markdown source.
    :returns: the heading text, or an empty string if there is none.
    """
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_words(text: str) -> set[str]:
    """Return the lower-case search words in ``text``.

    Stop words and one-letter words are dropped.

    :param text: markdown source.
    :returns: the distinct words.
    """
    words = set(WORD_RE.findall(text.lower()))
    return {w for w in words if len(w) > 1 and w not in STOP_WORDS}


def extract_links(text: str) -> list[str]:
    """Return the targets of ``[[wiki links]]`` in order of appearance.

    The heading part (``#...``) and the alias part (``|...``) are removed.
    A target that appears more than once is returned once.

    :param text: markdown source.
    :returns: the link targets.
    """
    seen = []
    for match in LINK_RE.finditer(text):
        target = match.group(1).strip()
        if target and target not in seen:
            seen.append(target)
    return seen
