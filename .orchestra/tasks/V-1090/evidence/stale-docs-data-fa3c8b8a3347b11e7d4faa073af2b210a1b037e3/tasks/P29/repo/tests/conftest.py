import pytest

CLUB_FILES = {
    "books.csv": (
        "book_id,title,author,pages\n"
        "solaris,Solaris,Stanislaw Lem,204\n"
        "middlemarch,Middlemarch,George Eliot,880\n"
    ),
    "members.csv": (
        "name,email,joined\n"
        "Rosa,rosa@example.com,2025-02-01\n"
        "Karl,karl@example.com,2025-02-01\n"
        "Ines,ines@example.com,2026-09-20\n"
    ),
    "journal.csv": (
        "day,member,book_id,page\n"
        "2026-09-12,Karl,solaris,90\n"
        "2026-09-05,Rosa,solaris,40\n"
        "2026-09-12,Rosa,solaris,150\n"
    ),
    "meetings.csv": (
        "day,book_id,host,place\n"
        "2026-10-15,middlemarch,Karl,Cafe Lindo\n"
        "2026-09-17,solaris,Rosa,Library room 2\n"
    ),
}


@pytest.fixture
def write_file(tmp_path):
    """Return a helper that writes a text file under tmp_path and returns its path as text."""

    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    return _write


@pytest.fixture
def club_dir(tmp_path):
    """Write the sample club folder and return its path."""
    folder = tmp_path / "club"
    folder.mkdir()
    for name, text in CLUB_FILES.items():
        (folder / name).write_text(text, encoding="utf-8")
    return str(folder)
