"""The reading journal: members note the page they have reached in a book."""
from datetime import date
from typing import NamedTuple

from bookclub.csvfiles import parse_count, parse_day, read_rows

COLUMNS = ("day", "member", "book_id", "page")


class JournalEntry(NamedTuple):
    """One line of the reading journal.

    :param day: the day of the entry
    :param member: name of the member
    :param book_id: id of the book
    :param page: the page the member has reached
    """

    day: date
    member: str
    book_id: str
    page: int


def load_journal(path: str) -> list[JournalEntry]:
    """Read the reading journal.

    :param path: path of ``journal.csv``
    :returns: the entries sorted by day; entries of the same day keep their file order
    :raises ValueError: if a row is invalid
    """
    entries: list[JournalEntry] = []
    for line_no, row in read_rows(path, COLUMNS):
        where = "{}:{}".format(path, line_no)
        entries.append(JournalEntry(
            day=parse_day(row["day"], where),
            member=row["member"],
            book_id=row["book_id"],
            page=parse_count(row["page"], where),
        ))
    entries.sort(key=lambda entry: entry.day)
    return entries


def entries_for_book(entries: list[JournalEntry], book_id: str) -> list[JournalEntry]:
    """Return the journal entries of one book.

    :param entries: journal entries
    :param book_id: id of the book
    :returns: the entries of that book, in the order given
    """
    return [entry for entry in entries if entry.book_id == book_id]
