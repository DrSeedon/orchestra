"""Column names: normalizing headers and comparing column sets."""

from csvmerge.errors import ColumnError


def normalize_name(name: str) -> str:
    """Trim a column name, fold it to lower case and join inner words with "_"."""
    return "_".join(name.strip().lower().split())


def normalize_header(names: list[str]) -> list[str]:
    """Normalize every name of a header row.

    A blank name or a name that appears twice raises ColumnError.
    """
    columns: list[str] = []
    for position, name in enumerate(names, start=1):
        column = normalize_name(name)
        if not column:
            raise ColumnError("column {} has no name".format(position))
        if column in columns:
            raise ColumnError("column {!r} appears twice".format(column))
        columns.append(column)
    return columns


def same_columns(first: list[str], second: list[str]) -> bool:
    """True when both headers have the same names, in any order."""
    return sorted(first) == sorted(second)


def describe_columns(columns: list[str]) -> str:
    """The column names as one comma-separated string, for messages."""
    return ", ".join(columns) if columns else "(none)"
