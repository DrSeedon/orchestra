# plantcare

plantcare keeps track of when the house plants need water. It reads a plant
file, shows which plants are due, and records each watering. The package has
no third-party dependencies.

## Layout

- `plantcare/settings.py` - the settings, their defaults and the settings file reader
- `plantcare/plants.py` - the `Plant` record, reading and writing the plant file
- `plantcare/schedule.py` - next watering day, days late, due plants, recording a watering
- `plantcare/history.py` - the watering history file
- `plantcare/cli.py` - the command line (`list`, `due`, `water`)
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. Install pytest to run the tests; nothing else is needed.

## Running tests

```
python -m pytest -q
```

Run it from the repository root. Tests write files only to temporary folders.

## Usage

```
python -m plantcare.cli --settings home.cfg list
python -m plantcare.cli --settings home.cfg due
python -m plantcare.cli --settings home.cfg --date 2026-07-10 water Fern Basil
```

The settings file has one `key = value` line per setting. Blank lines and
lines that start with `#` are skipped. The known settings are `plants_file`
(default `plants.json`), `default_interval` (default 7 days) and
`history_file` (no history when it is not set).

The plant file is JSON: `{"plants": [{"name": "Fern", "interval": 3,
"last_watered": "2026-07-08", "spot": "bathroom"}]}`. A plant without an
interval gets `default_interval`. Commands write a message to stderr and exit
with status 2 when an input cannot be read.

## Conventions

- Settings are a plain dict of setting name to value. Read a setting with
  `settings["plants_file"]`. A new setting is a new key with a default in
  `plantcare/settings.py`.
- A value that can be missing is annotated as `X | None`, for example
  `last_watered: date | None = None`. Do not use `typing.Optional`.
- Container annotations use `typing.List` and `typing.Dict`, for example
  `List[Plant]` and `Dict[str, int]`.
- Build text with `str.format()`, for example
  `"{}: every {} days".format(name, interval)`. Do not use f-strings.
- File paths are plain strings. Work with them through `os.path` and `os`
  (`os.path.join`, `os.path.exists`, `os.makedirs`). Do not use `pathlib`.
- Dates are `datetime.date` values. In files and on the command line they are
  ISO text, `YYYY-MM-DD`.
- Standard library only. JSON files are written with `indent=2`.
