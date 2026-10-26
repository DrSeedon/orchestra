"""Build, save and load the word index of a notes folder."""

import json
import sys
from pathlib import Path

from notegrep.notes import load_notes
from notegrep.parse import extract_words

INDEX_FILE = ".notegrep-index.json"


def build_index(root: Path) -> dict[str, list[str]]:
    """Map every search word to the names of the notes that contain it.

    :param root: the notes folder.
    :returns: word to sorted list of note names.
    """
    index: dict[str, set[str]] = {}
    for note in load_notes(root):
        for word in extract_words(note.title + "\n" + note.text):
            index.setdefault(word, set()).add(note.name)
    return {word: sorted(names) for word, names in sorted(index.items())}


def index_path(root: Path) -> Path:
    """Return the location of the saved index for a notes folder.

    :param root: the notes folder.
    :returns: the index file location.
    """
    return Path(root) / INDEX_FILE


def save_index(index: dict[str, list[str]], root: Path) -> Path:
    """Write the index as JSON into the notes folder.

    :param index: the index from :func:`build_index`.
    :param root: the notes folder.
    :returns: the file that was written.
    """
    target = index_path(root)
    target.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    return target


def load_index(root: Path) -> dict[str, list[str]]:
    """Read the saved index of a notes folder.

    A missing or damaged index file gives an empty index and a warning.

    :param root: the notes folder.
    :returns: the saved index, or an empty one.
    """
    source = index_path(root)
    if not source.exists():
        print(f"warning: no index at {source}; run build first", file=sys.stderr)
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"warning: damaged index {source}: {exc}", file=sys.stderr)
        return {}
