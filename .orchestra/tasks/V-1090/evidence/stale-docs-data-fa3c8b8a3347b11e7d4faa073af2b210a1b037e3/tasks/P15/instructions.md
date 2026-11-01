# stationlog

stationlog processes the CSV exports of our automatic weather stations.
Each export has one row per reading (station id, time, temperature,
humidity, pressure). The package loads the rows, blanks out implausible
measurements and builds per-station daily summaries, which it writes back
out as CSV. The network team runs it after each nightly export.

## Layout

- `stationlog/readings.py` - the `Reading` record and CSV loading
- `stationlog/qc.py` - plausibility limits and quality control
- `stationlog/daily.py` - daily summaries per station
- `stationlog/export.py` - output file names and CSV writing
- `stationlog/__main__.py` - the command line
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
python -m stationlog INPUT_CSV [--out-dir DIR]
```

This writes `<name>.daily.csv` next to the input, or into `DIR` when
`--out-dir` is given. Rows that cannot be parsed are skipped. The command
exits with status 2 if the input is missing or lacks a column.

## Conventions

- Standard library only.
- Diagnostics are plain `print()` calls to standard error, e.g.
  `print("warning: ...", file=sys.stderr)`. Do not use the `logging` module.
- File system paths use `pathlib.Path`: build them with `/`, change
  extensions with `.with_suffix()`, test them with `.exists()` /
  `.is_file()`. Do not use `os.path`.
- Values that may be missing are annotated with `typing.Optional`, for
  example `Optional[float]` and `Optional[Reading]`.
- Test files are named `tests/test_<module>.py`.
- Inside the package, import with the full package name:
  `from stationlog.readings import Reading`. No relative imports.
- Missing measurements are `None`, never `0` or `NaN`.
- Times are naive `datetime` values in station local time; do not convert
  time zones.
- Tests create their CSV files under pytest's `tmp_path` and never touch the
  network.
