# meterread

meterread reads electricity meter readings from a CSV file and works out the
energy each meter used. It also prices that energy with a unit price and a
daily standing charge taken from a settings file.

## Layout

- `meterread/money.py` - parses, rounds and formats money amounts
- `meterread/settings.py` - the settings, their defaults and the settings file loader
- `meterread/readings.py` - reads the readings file and checks the readings of a meter
- `meterread/usage.py` - usage per meter and the flat-rate cost
- `meterread/cli.py` - the command line (usage, cost)
- `tests/` - pytest tests, one file per module

A readings file is a CSV file with the header `meter,date,kwh`. The kwh column
holds the counter value of the meter in whole kWh. A settings file holds
`key = value` lines for `currency`, `unit_price` and `standing_charge`; lines
that start with `#` are comments.

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

## Usage

```
python -m meterread.cli usage READINGS_CSV
python -m meterread.cli cost READINGS_CSV [--settings FILE]
```

Both commands exit with status 2 when a file is missing or broken, or when the
readings of a meter go down or a meter has two readings on one day.

## Conventions

- Standard library only. pytest is the only development dependency.
- Money is a whole number of cents in an `int`, for example
  `standing_charge_cents = 45` for 0.45. Turn cents into text like `12.30`
  only when writing output.
- Settings are a plain dict with one key per setting. Read a setting as
  `settings["standing_charge"]`.
- Report bad input by raising `ValueError` with a message that names the
  problem, for example `raise ValueError(f"bad date {text!r}")`. The command
  line catches it and exits with status 2.
- Every public function has a Google-style docstring: a one-line summary,
  then `Args:` and `Returns:` sections.
- Write a value that may be missing as `Optional[X]` from `typing`, for
  example `def check_meter(readings: list[Reading]) -> Optional[str]`.
- Dates are ISO `YYYY-MM-DD`. Meter values are whole kWh.
- Tests that need files create them under pytest's `tmp_path`.
