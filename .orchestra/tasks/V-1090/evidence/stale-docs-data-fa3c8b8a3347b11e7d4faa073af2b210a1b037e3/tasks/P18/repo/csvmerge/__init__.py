"""Tools for combining CSV exports into one file."""

from csvmerge.reader import Table, read_table
from csvmerge.writer import write_table

__all__ = ["Table", "read_table", "write_table"]
__version__ = "1.2.0"
