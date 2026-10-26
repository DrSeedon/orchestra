# cronlint

cronlint parses cron expressions and reads crontab files. It turns each
expression into a `Schedule` that knows which minutes, hours, days, months
and weekdays it matches, and it can list the next runs of a schedule. A small
command line checks a crontab and shows upcoming runs.

## Layout

- `cronlint/fields.py` - the five cron fields, their value ranges, month and weekday names, macros such as `@daily`
- `cronlint/parser.py` - parses field text and whole expressions into a `Schedule`
- `cronlint/schedule.py` - `Schedule`: matching a time and finding the next runs
- `cronlint/crontab.py` - reads a crontab file into `CrontabEntry` records
- `cronlint/errors.py` - error types
- `cronlint/cli.py` - the command line (check, next)
- `tests/` - pytest tests, one file per module

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
python -m cronlint.cli check CRONTAB
python -m cronlint.cli next CRONTAB [--start "2026-01-05 08:00"] [--count 3]
```

`check` exits with status 1 when an entry does not parse. Both commands exit
with status 2 when the crontab cannot be read.

## Conventions

- Standard library only. pytest is the only development dependency.
- Fixed sets of values are `Enum` classes, for example
  `class Field(Enum)` with members `MINUTE = "minute"` and `HOUR = "hour"`.
  Compare against the members, not against bare strings.
- Signal bad input with built-in exceptions: `ValueError` for a bad value,
  for example `raise ValueError("minute: 61 is outside 0-59")`, and
  `KeyError` for an unknown name. Do not add project-specific exception
  classes.
- A value that can be missing is typed `X | None`, for example
  `def next_run(self, start: datetime) -> datetime | None`.
- Build text with `str.format`, for example
  `"line {}: {}".format(entry.line, message)`.
- Day of week 0 is Sunday. The parser also accepts 7 for Sunday and stores
  it as 0.
- Library code never reads the clock. Functions take the start time as an
  argument; only `cli.py` calls `datetime.now()`.
- Tests that need a crontab file write it under pytest's `tmp_path`.
