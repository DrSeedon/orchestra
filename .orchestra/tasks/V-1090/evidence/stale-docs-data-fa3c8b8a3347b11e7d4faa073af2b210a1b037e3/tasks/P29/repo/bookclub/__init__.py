"""bookclub: the books, members, reading journal and meetings of our book club."""
from bookclub.books import Book, load_books
from bookclub.club import Club, load_club
from bookclub.journal import JournalEntry, load_journal
from bookclub.meetings import Meeting, load_meetings, next_meeting
from bookclub.members import Member, load_members

__version__ = "1.2.0"
