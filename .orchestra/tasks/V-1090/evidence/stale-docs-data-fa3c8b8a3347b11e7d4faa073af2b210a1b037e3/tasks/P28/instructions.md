# sensorhub

sensorhub summarizes the readings of the temperature and humidity sensors in
our buildings. It reads a CSV export of readings and writes a JSON summary
with, per sensor, the number of readings, the lowest, highest and mean value,
the time of the last reading and the number of gaps in the data.

## Layout

- `sensorhub/settings.py` - reads the settings file (INI, section `[sensorhub]`)
- `sensorhub/readings.py` - reads the readings CSV, skips and reports bad rows
- `sensorhub/stats.py` - groups readings by sensor and computes the statistics
- `sensorhub/report.py` - builds and writes the JSON summary
- `sensorhub/__main__.py` - the command line entry point
- `tests/` - pytest tests; shared fixtures and sample data in `conftest.py`

## Setup

Python 3.10 or newer, standard library only. Install pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m sensorhub READINGS OUTPUT [--settings FILE]
```

READINGS is a CSV file with the columns `time,sensor,value`; times are ISO
`YYYY-MM-DDTHH:MM:SS`. The settings file is an INI file:

```
[sensorhub]
max_gap = 30
decimals = 1
min_readings = 3
```

All settings are whole numbers, times are in minutes, and settings that the
file does not name keep the values shown above. The command exits with
status 2 when an input file cannot be read or a setting is invalid.

## Conventions

- Settings are a plain dict that maps the setting name to its value. Read a
  setting with `settings["max_gap"]`, or `settings.get("decimals", 1)` when a
  default applies. Do not wrap settings in a class with attributes.
- Report skipped rows, warnings and progress through the `logging` module:
  `logger = logging.getLogger(__name__)` in each module, then
  `logger.warning(...)` or `logger.info(...)`. Do not use `print()`.
- A function that gets invalid input raises an exception with a clear
  message, for example `raise ValueError(f"bad value {text!r}")`; the command
  line catches it and exits with status 2. Do not return `(result, error)` pairs.
- Write optional types with `typing.Optional`, for example
  `path: Optional[str] = None`. Do not write `str | None`.
- Readings are sorted by time right after loading; the rest of the code
  relies on that order.
- Times are naive local times, parsed with `datetime.fromisoformat`.
