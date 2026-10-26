# habitlog

habitlog keeps a plain text log of the habits we do every day and checks each
week against a weekly target per habit. Every line of the log names a day and
one habit done on that day. The weekly command counts the days per habit in
one week and writes a small CSV file with the habits that met their target.

## Layout

- `habitlog/dates.py` - parsing days (YYYY-MM-DD) and the days of a week
- `habitlog/entries.py` - log entries, parsing a log line, reading the log file
- `habitlog/stats.py` - selecting entries by day and the days per habit
- `habitlog/targets.py` - the targets file (habit,per_week)
- `habitlog/weekly.py` - the weekly command
- `tests/` - tests; stats is covered in `tests/test_entries.py`

## Setup

Python 3.10 or newer. Only the standard library is used; install pytest to
run the tests.

## Running tests

```
python -m pytest -q
```

Run it from the repository root.

## Usage

```
python -m habitlog.weekly LOG TARGETS OUTPUT [--day DAY]
```

LOG is the habit log, for example:

```
# May
2024-05-01 run
2024-05-01 read
2024-05-02 run
```

Blank lines and lines that start with `#` are skipped. TARGETS is a CSV file
with the columns habit,per_week. The week runs from Monday to Sunday and
contains DAY; without `--day` it is the week of the latest day in the log.

## Conventions

- Standard library only.
- Records are frozen dataclasses, for example
  `@dataclass(frozen=True) class Entry` with typed fields. Do not use
  `NamedTuple` or `collections.namedtuple`.
- Functions that can fail on bad input do not raise. They return a pair
  `(value, error)`: `(result, None)` on success and `(None, "message")` on
  failure. The caller checks the error before it uses the value.
- Write a value that may be missing as `X | None`, for example
  `last: date | None = None`. Do not use `typing.Optional`.
- Annotate collections with the `typing` generics, for example
  `List[Entry]` or `Dict[str, List[date]]`. Do not write `list[Entry]` or
  `dict[str, int]`.
- Tests are `unittest.TestCase` classes, one class per function under test,
  with `self.assertEqual` and `self.assertRaises`. Do not write bare test
  functions.
- Habit names are lower case with single spaces between words.
- A habit counts once per day, even when it is logged twice on that day.
- Command-line tools exit with status 2 on bad input and write the reason
  to stderr.
