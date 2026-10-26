# bookclub

bookclub keeps the records of our book club in a folder of CSV files: the
books we read, the members, a reading journal in which members note the page
they have reached, and the meeting plan. It checks that the files fit
together and writes the agenda for the next meeting.

## Layout

- `bookclub/csvfiles.py` - reads a CSV file with a required header; parses dates and page numbers
- `bookclub/books.py` - the book list (`books.csv`)
- `bookclub/members.py` - the member list (`members.csv`) and who had joined by a given day
- `bookclub/journal.py` - the reading journal (`journal.csv`)
- `bookclub/meetings.py` - the meeting plan (`meetings.csv`) and the next meeting
- `bookclub/club.py` - loads a whole club folder and checks that named books and members exist
- `bookclub/agenda.py` - command line: writes the agenda of the next meeting
- `tests/` - tests per module; `conftest.py` writes a sample club folder

## Setup

Python 3.10 or newer, standard library only. Install pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m bookclub.agenda CLUB_DIR DATE OUTPUT
```

CLUB_DIR holds `books.csv`, `members.csv`, `journal.csv` and `meetings.csv`
with these headers:

- `books.csv`: `book_id,title,author,pages`
- `members.csv`: `name,email,joined`
- `journal.csv`: `day,member,book_id,page`
- `meetings.csv`: `day,book_id,host,place`

DATE is `YYYY-MM-DD`. The command writes the agenda of the first meeting on or
after that day to OUTPUT. It exits with status 2 when a file cannot be read or
is invalid, or when no meeting is planned.

## Conventions

- Records are frozen dataclasses with one typed field per column:
  `@dataclass(frozen=True)` on `class Book:` with `book_id: str`, `pages: int`.
  Do not use `NamedTuple` or `collections.namedtuple`.
- Modules inside the package import each other with relative imports, for
  example `from .csvfiles import read_rows`. Do not write `from bookclub.csvfiles import ...`.
- Docstrings use the Google format with `Args:` and `Returns:` sections:

  ```
  def load_books(path: str) -> dict[str, Book]:
      """Read the book list of the club.

      Args:
          path: Path of books.csv.

      Returns:
          The books by id, in file order.
      """
  ```

- Tests are unittest classes, one class per function or command under test:
  `class TestLoadBooks(unittest.TestCase)` with `self.assertEqual(...)` and
  `self.assertRaises(...)`. pytest collects and runs them.
- Build text with f-strings: `f"{path}:{line_no}: bad date {text!r}"`. Do not
  use `str.format()` or `%` formatting.
- Every loader reads its file through `csvfiles.read_rows`, which checks the
  header and strips the values. Dates are ISO `YYYY-MM-DD`.
- Invalid input raises `ValueError` with the file name and line number. The
  command line catches `OSError` and `ValueError` and exits with status 2.
- Type hints use the built-in generics and `X | None`: `list[Member]`,
  `dict[str, Book]`, `Meeting | None`.
