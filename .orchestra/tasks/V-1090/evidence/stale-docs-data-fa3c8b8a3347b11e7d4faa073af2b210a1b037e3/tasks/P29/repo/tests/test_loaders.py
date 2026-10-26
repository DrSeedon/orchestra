import os
from datetime import date

import pytest

from bookclub.books import Book, load_books
from bookclub.journal import entries_for_book, load_journal
from bookclub.meetings import load_meetings, next_meeting
from bookclub.members import load_members, members_on


def test_load_books(club_dir):
    books = load_books(os.path.join(club_dir, "books.csv"))
    assert list(books) == ["solaris", "middlemarch"]
    assert books["solaris"] == Book("solaris", "Solaris", "Stanislaw Lem", 204)
    assert books["solaris"].label() == "Solaris by Stanislaw Lem"


def test_load_books_rejects_duplicates_and_empty_books(write_file):
    path = write_file("books.csv", "book_id,title,author,pages\na,A,X,10\na,B,Y,20\n")
    with pytest.raises(ValueError, match="books.csv:3: book a is listed twice"):
        load_books(path)
    path = write_file("books.csv", "book_id,title,author,pages\na,A,X,0\n")
    with pytest.raises(ValueError, match="has no pages"):
        load_books(path)


def test_members_on(club_dir):
    members = load_members(os.path.join(club_dir, "members.csv"))
    assert [m.name for m in members] == ["Rosa", "Karl", "Ines"]
    assert [m.name for m in members_on(members, date(2026, 9, 17))] == ["Karl", "Rosa"]


def test_load_journal_sorts_by_day(club_dir):
    entries = load_journal(os.path.join(club_dir, "journal.csv"))
    assert [(e.member, e.page) for e in entries] == [("Rosa", 40), ("Karl", 90), ("Rosa", 150)]
    assert entries_for_book(entries, "middlemarch") == []


def test_next_meeting(club_dir):
    meetings = load_meetings(os.path.join(club_dir, "meetings.csv"))
    assert next_meeting(meetings, date(2026, 9, 17)).book_id == "solaris"
    assert next_meeting(meetings, date(2026, 9, 18)).book_id == "middlemarch"
    assert next_meeting(meetings, date(2026, 10, 16)) is None
