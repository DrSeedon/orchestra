"""Reading the CSV input files."""

import csv


def read_rows(path: str, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """Read a CSV file with a header row.

    Args:
        path: the file to read.
        columns: the columns the file must have; other columns are ignored.

    Returns:
        The line number and the trimmed values of every row that is not blank.

    Raises:
        ValueError: if one of the columns is missing.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [name for name in columns if name not in header]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        rows = []
        for row in reader:
            values = {name: (row[name] or "").strip() for name in columns}
            if any(values.values()):
                rows.append((reader.line_num, values))
    return rows
