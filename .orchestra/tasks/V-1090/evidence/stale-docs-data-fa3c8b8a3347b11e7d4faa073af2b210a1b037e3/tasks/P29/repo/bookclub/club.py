"""Loading a whole club folder and checking that its files fit together."""
import os
from typing import NamedTuple

from bookclub.books import Book, load_books
from bookclub.journal import JournalEntry, load_journal
from bookclub.meetings import Meeting, load_meetings
from bookclub.members import Member, load_members

BOOKS_FILE = "books.csv"
MEMBERS_FILE = "members.csv"
JOURNAL_FILE = "journal.csv"
MEETINGS_FILE = "meetings.csv"


class Club(NamedTuple):
    """Everything in a club folder.

    :param books: the books by id
    :param members: the members in file order
    :param journal: the journal entries sorted by day
    :param meetings: the meetings sorted by day
    """

    books: dict[str, Book]
    members: list[Member]
    journal: list[JournalEntry]
    meetings: list[Meeting]


def check_club(club: Club) -> None:
    """Check that the journal and the meetings only name known books and members.

    :param club: the loaded club
    :raises ValueError: on the first unknown book or member
    """
    names = {member.name for member in club.members}
    for entry in club.journal:
        if entry.member not in names:
            raise ValueError("{}: journal entry of unknown member {}".format(JOURNAL_FILE, entry.member))
        if entry.book_id not in club.books:
            raise ValueError("{}: journal entry for unknown book {}".format(JOURNAL_FILE, entry.book_id))
    for meeting in club.meetings:
        if meeting.book_id not in club.books:
            raise ValueError("{}: meeting on {} for unknown book {}".format(
                MEETINGS_FILE, meeting.day.isoformat(), meeting.book_id))
        if meeting.host not in names:
            raise ValueError("{}: meeting on {} hosted by unknown member {}".format(
                MEETINGS_FILE, meeting.day.isoformat(), meeting.host))


def load_club(folder: str) -> Club:
    """Read all files of a club folder and check them.

    :param folder: the club folder with ``books.csv``, ``members.csv``,
        ``journal.csv`` and ``meetings.csv``
    :returns: the club
    :raises OSError: if a file cannot be read
    :raises ValueError: if a file is invalid or the files do not fit together
    """
    club = Club(
        books=load_books(os.path.join(folder, BOOKS_FILE)),
        members=load_members(os.path.join(folder, MEMBERS_FILE)),
        journal=load_journal(os.path.join(folder, JOURNAL_FILE)),
        meetings=load_meetings(os.path.join(folder, MEETINGS_FILE)),
    )
    check_club(club)
    return club
