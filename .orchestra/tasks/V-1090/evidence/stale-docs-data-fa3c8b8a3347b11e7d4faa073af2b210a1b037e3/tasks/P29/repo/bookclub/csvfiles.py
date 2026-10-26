"""Reading the CSV files of a club folder."""
import csv
from datetime import date


def read_rows(path: str, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """Read a CSV file and return its rows together with their line numbers.

    :param path: path of the CSV file
    :param columns: names of the columns that the header must contain
    :returns: ``(line number, row)`` pairs in file order, with stripped values
    :raises ValueError: if the header lacks one of the columns
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [name for name in columns if name not in header]
        if missing:
            raise ValueError("{}: missing columns {}".format(path, ", ".join(missing)))
        rows = []
        for line_no, row in enumerate(reader, start=2):
            rows.append((line_no, {name: (row.get(name) or "").strip() for name in columns}))
    return rows


def parse_day(text: str, where: str) -> date:
    """Parse an ISO date such as ``2026-09-14``.

    :param text: the text of the date
    :param where: file and line number, used in the error message
    :returns: the date
    :raises ValueError: if the text is not an ISO date
    """
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError("{}: bad date {!r}".format(where, text)) from None


def parse_count(text: str, where: str) -> int:
    """Parse a whole number that is not negative, such as a page number.

    :param text: the text of the number
    :param where: file and line number, used in the error message
    :returns: the number
    :raises ValueError: if the text is not a whole number or is negative
    """
    try:
        value = int(text)
    except ValueError:
        raise ValueError("{}: bad number {!r}".format(where, text)) from None
    if value < 0:
        raise ValueError("{}: number must not be negative, got {}".format(where, value))
    return value
