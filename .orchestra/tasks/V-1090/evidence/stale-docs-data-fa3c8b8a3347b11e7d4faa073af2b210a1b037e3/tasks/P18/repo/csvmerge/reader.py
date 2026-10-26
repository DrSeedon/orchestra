"""Reading CSV files into tables."""

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from csvmerge.columns import normalize_header
from csvmerge.errors import CsvReadError

logger = logging.getLogger(__name__)

DELIMITERS = ",;\t|"


@dataclass
class Table:
    """The normalized header and the rows of one CSV file."""

    name: str
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)


def sniff_delimiter(header_line: str) -> str:
    """The delimiter that occurs most often in the header line; a comma on a tie."""
    return max(DELIMITERS, key=header_line.count)


def read_table(path: str | Path) -> Table:
    """Read a CSV file that starts with a header row.

    The file is read as UTF-8, with or without a byte order mark. Values are
    trimmed and blank lines are skipped. A file that cannot be read, an empty
    file and a row with a different number of fields than the header raise
    CsvReadError; a bad header raises ColumnError.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as err:
        raise CsvReadError("{}: cannot read file ({})".format(source.name, err)) from err
    if not text.strip():
        raise CsvReadError("{}: file is empty".format(source.name))

    delimiter = sniff_delimiter(text.splitlines()[0])
    records = csv.reader(io.StringIO(text), delimiter=delimiter)
    columns = normalize_header(next(records))
    table = Table(source.name, columns)
    for record in records:
        if not any(value.strip() for value in record):
            continue
        if len(record) != len(columns):
            raise CsvReadError("{}:{}: expected {} fields, found {}".format(
                source.name, records.line_num, len(columns), len(record)))
        table.rows.append(dict(zip(columns, (value.strip() for value in record))))
    logger.debug("read {} rows from {} ({!r} delimited)".format(len(table.rows), source.name, delimiter))
    return table
