"""Errors raised by csvmerge."""


class CsvMergeError(Exception):
    """Base class of all csvmerge errors."""


class CsvReadError(CsvMergeError):
    """A file cannot be read as a CSV table."""


class ColumnError(CsvMergeError):
    """A header or a set of columns cannot be used."""
