# csvmerge

csvmerge combines CSV exports from our shop systems into one file for the
weekly stock review. It reads files with a header row, detects the delimiter
(comma, semicolon, tab or pipe) and normalizes the column names, so that
"Unit Price" and "unit_price" name the same column.

## Layout

- `csvmerge/errors.py` - error types for unreadable files and unusable columns
- `csvmerge/columns.py` - column name normalization and header checks
- `csvmerge/reader.py` - the `Table` record and `read_table`, which reads one CSV file
- `csvmerge/writer.py` - `write_table`, which writes rows under a header
- `csvmerge/concat.py` - the concat command
- `tests/` - pytest tests, one file per module

## Setup

Python 3.10 or newer. Only the standard library is used; install pytest to
run the tests.

## Running tests

```
python -m pytest -q
```

## Usage

```
python -m csvmerge.concat OUTPUT FILE [FILE ...] [--verbose]
```

All input files must have the same columns, in any order. The rows are
written file by file under the header of the first file.

## Conventions

- Standard library only.
- Tell the user what a command did with `print()`, for example
  `print(f"wrote {count} rows to {target}")`. Do not use the `logging`
  module.
- Handle file and folder names as plain strings with `os.path` and `os`,
  for example `os.path.join(folder, name)` and `os.listdir(folder)`. Do not
  use `pathlib`.
- Report bad input by raising a built-in exception, for example
  `raise ValueError(f"{name}: no column {key!r}")`. Do not define
  exception classes of our own.
- Build messages with f-strings, for example `f"read {count} rows from {name}"`.
  Do not use `str.format()`.
- Inside the package, import sibling modules with relative imports, for
  example `from .reader import read_table`. Do not write
  `from csvmerge.reader import read_table`.
- Compare column names only after `normalize_name`; the reader returns
  normalized names already.
- Output files are comma-separated, with `\n` line endings. `write_table`
  creates missing parent folders.
- Commands exit with status 2 on bad input.
