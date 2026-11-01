"""Find note files in a notes folder and read them."""

import sys
from dataclasses import dataclass
from pathlib import Path

from notegrep.parse import extract_title

NOTE_SUFFIX = ".md"


@dataclass
class Note:
    """One markdown note loaded from disk."""

    path: Path
    name: str
    title: str
    text: str


def find_notes(root: Path) -> list[Path]:
    """Return all markdown files below ``root``, sorted by path.

    Files and folders whose name starts with a dot are skipped.

    :param root: the notes folder.
    :returns: the note files, sorted.
    :raises NotADirectoryError: if ``root`` is not a folder.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    found = []
    for path in root.rglob("*" + NOTE_SUFFIX):
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        found.append(path)
    return sorted(found)


def note_name(path: Path) -> str:
    """Return the note name used in links: the file name without suffix.

    :param path: the note file.
    :returns: the note name.
    """
    return Path(path).stem


def read_note(path: Path) -> Note | None:
    """Read one note file.

    A file that cannot be read or is not valid UTF-8 is skipped with a warning.

    :param path: the note file.
    :returns: the loaded note, or ``None`` if the file was skipped.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"warning: skipping {path}: {exc}", file=sys.stderr)
        return None
    name = note_name(path)
    return Note(path=path, name=name, title=extract_title(text) or name, text=text)


def load_notes(root: Path) -> list[Note]:
    """Read every note below ``root``.

    :param root: the notes folder.
    :returns: the notes that could be read, sorted by path.
    """
    notes = []
    for path in find_notes(root):
        note = read_note(path)
        if note is not None:
            notes.append(note)
    return notes
