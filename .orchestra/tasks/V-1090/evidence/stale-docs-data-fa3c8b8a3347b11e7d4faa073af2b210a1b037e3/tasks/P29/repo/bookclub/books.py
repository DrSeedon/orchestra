"""The list of books the club reads."""
from typing import NamedTuple

from bookclub.csvfiles import parse_count, read_rows

COLUMNS = ("book_id", "title", "author", "pages")


class Book(NamedTuple):
    """A book on the club list.

    :param book_id: short id that the other club files use, for example ``dune``
    :param title: title of the book
    :param author: author of the book
    :param pages: number of pages, at least 1
    """

    book_id: str
    title: str
    author: str
    pages: int

    def label(self) -> str:
        """Return the book for display.

        :returns: text such as ``Dune by Frank Herbert``
        """
        return "{} by {}".format(self.title, self.author)


def load_books(path: str) -> dict[str, Book]:
    """Read the book list of the club.

    :param path: path of ``books.csv``
    :returns: the books by id, in file order
    :raises ValueError: if a row is invalid or a book id is listed twice
    """
    books: dict[str, Book] = {}
    for line_no, row in read_rows(path, COLUMNS):
        where = "{}:{}".format(path, line_no)
        book_id = row["book_id"]
        if not book_id:
            raise ValueError("{}: book_id is empty".format(where))
        if book_id in books:
            raise ValueError("{}: book {} is listed twice".format(where, book_id))
        pages = parse_count(row["pages"], where)
        if pages == 0:
            raise ValueError("{}: book {} has no pages".format(where, book_id))
        books[book_id] = Book(book_id, row["title"], row["author"], pages)
    return books
