"""Concatenate CSV files that have the same columns.

Usage: python -m csvmerge.concat OUTPUT FILE [FILE ...]
"""

import argparse
import logging
import sys

from csvmerge.columns import describe_columns, same_columns
from csvmerge.errors import ColumnError, CsvMergeError
from csvmerge.reader import Table, read_table
from csvmerge.writer import write_table

logger = logging.getLogger(__name__)


def concat_tables(tables: list[Table]) -> list[dict[str, str]]:
    """All rows of the tables, file by file.

    Every table must have the columns of the first one, in any order;
    otherwise ColumnError is raised.
    """
    first = tables[0]
    rows: list[dict[str, str]] = []
    for table in tables:
        if not same_columns(table.columns, first.columns):
            raise ColumnError("{} has columns {} but {} has {}".format(
                table.name, describe_columns(table.columns), first.name, describe_columns(first.columns)))
        rows.extend(table.rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m csvmerge.concat",
                                     description="Concatenate CSV files with the same columns.")
    parser.add_argument("output", help="CSV file to write")
    parser.add_argument("files", nargs="+", help="CSV files to read, in this order")
    parser.add_argument("--verbose", action="store_true", help="report every file that is read")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")

    try:
        tables = [read_table(name) for name in args.files]
        rows = concat_tables(tables)
    except CsvMergeError as err:
        logger.error("cannot concatenate: {}".format(err))
        return 2
    target = write_table(args.output, tables[0].columns, rows)
    logger.info("wrote {} rows from {} files to {}".format(len(rows), len(tables), target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
