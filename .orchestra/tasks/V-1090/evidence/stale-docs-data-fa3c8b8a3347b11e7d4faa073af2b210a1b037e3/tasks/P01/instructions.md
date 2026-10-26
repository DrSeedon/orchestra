# invoice-tool

invoice-tool reads the CSV invoice exports we receive from suppliers and turns
them into one normalized record format: supplier, invoice number, ISO date,
amount in cents and currency. Each supplier names its columns and writes dates
and amounts differently. This package hides those differences, so the
accounting side only ever sees clean records.

## Layout

- `invoice_tool/parser.py` - reads a supplier CSV and maps its headers to our column names
- `invoice_tool/normalize.py` - parses dates and amounts, builds normalized records
- `invoice_tool/suppliers.py` - derives the supplier from a file name, applies aliases
- `invoice_tool/export.py` - writes normalized records to CSV
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. Tests write files only under
pytest's `tmp_path`.

## Conventions

- Standard library only. pytest is the only development dependency.
- Handle file system paths with `pathlib.Path`. Build paths with the `/`
  operator and use `Path` methods (`exists()`, `glob()`, `read_text()`).
  Do not use `os.path` or string concatenation for paths.
- Report diagnostics through the `logging` module. Each module defines
  `logger = logging.getLogger(__name__)` and reports skipped rows, skipped
  files and progress with `logger.warning(...)` and `logger.info(...)`.
  Do not use `print()`.
- Signal errors with the package's own exception classes. They all derive from
  one base class, `InvoiceError`; for example `InvoiceParseError` is for input
  that cannot be read or parsed. Do not raise built-in exceptions such as
  `ValueError`.
- Money is stored as integer cents (`amount_cents`), never as floats in records.
- Keep lines under 100 characters and keep functions short.
- Test files live in `tests/` and are named `test_<module>.py`, for example
  `tests/test_parser.py`.
