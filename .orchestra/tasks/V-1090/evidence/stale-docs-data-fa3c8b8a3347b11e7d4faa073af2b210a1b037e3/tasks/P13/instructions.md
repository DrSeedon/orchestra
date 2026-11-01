# metricroll

metricroll turns raw metric samples (`<metric> <unix-seconds> <value>` lines
exported by our collectors) into fixed-width windows and computes count,
min, max, mean, median and 95th percentile per window. The results feed the
nightly capacity report, which is plain text.

## Layout

- `metricroll/series.py` - the `Sample` record, line parsing, grouping by metric
- `metricroll/stats.py` - percentiles and the `Summary` record
- `metricroll/windows.py` - window boundaries and roll-ups per metric
- `metricroll/report.py` - text lines for the capacity report, and its command
- `tests/` - one test file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m metricroll.report SAMPLES OUTPUT [--width SECONDS]
```

The command reads the samples file, rolls every metric up into windows of
`--width` seconds (300 by default) and writes the report lines to OUTPUT.
Blank lines and `#` comments in SAMPLES are skipped. It exits with status 2
if SAMPLES is missing or has a bad line.

## Conventions

- Standard library only.
- Type hints use the built-in generic types: `list[float]`,
  `dict[str, list[Sample]]`, `tuple[int, Summary]`. Do not import `List`,
  `Dict` or `Tuple` from `typing`.
- Record and value types are dataclasses: `@dataclass(frozen=True)` with
  typed fields.
- Build output strings with `str.format()`, for example
  `"{} p95={:.2f}".format(name, value)`. Do not use f-strings.
- Tests are plain pytest functions (`def test_...():`) with bare `assert`
  statements and `pytest.raises` for errors. Do not write
  `unittest.TestCase` classes.
- Timestamps are `int` unix seconds everywhere. Window starts are multiples
  of the window width.
- `stats.py` and `windows.py` are pure functions with no I/O.
- Line length is 100 characters.
