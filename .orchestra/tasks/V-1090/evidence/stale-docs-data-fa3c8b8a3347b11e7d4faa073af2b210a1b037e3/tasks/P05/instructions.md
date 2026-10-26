# logsift

logsift reads the plain-text logs our services write and turns them into
short summaries for on-call reviews. It parses each line into a `LogEntry`
(timestamp, level, source, message and `key=value` fields), filters entries
by level, source or time window, and builds a text report with level counts,
error rate, busiest sources and the most common messages.

## Layout

- `logsift/parser.py` - parses one line into a `LogEntry`; level names
- `logsift/reader.py` - reads files, skips and reports unparsable lines
- `logsift/filters.py` - level, source, time window and text filters
- `logsift/summary.py` - counts, rates, common message shapes
- `logsift/report.py` - the text summary report and its command
- `tests/` - tests for each module

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m logsift.report [--top N] FILE [FILE ...]
```

prints the summary report of the given files to stdout. The command exits
with status 2 when a file does not exist.

## Conventions

- Standard library only.
- Every function in `logsift/` is fully type-annotated.
- Use built-in generic types in annotations: `list[LogEntry]`,
  `dict[str, int]`, `tuple[str, int]`. Do not import `List`, `Dict` or
  `Tuple` from `typing`.
- Inside the package, import sibling modules with relative imports, for
  example `from .parser import LogEntry`.
- Report warnings and diagnostics with the `logging` module. Each module
  defines `logger = logging.getLogger(__name__)` and calls
  `logger.warning(...)` or `logger.info(...)`. Library code does not call
  `print()`; only the report output goes to stdout.
- A malformed log line never stops a run: skip the line and report it.
- Tests are plain pytest functions that use bare `assert` statements. Use
  `pytest.raises` for expected errors and the `tmp_path` fixture for files.
  Do not write `unittest.TestCase` classes.
- Keep functions short; one function does one job.
