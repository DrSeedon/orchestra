# fuelcost

fuelcost works out the fuel cost of the trips of our car pool. It reads a
trips file and a vehicles file, prices each trip from its distance, the
consumption of the car and the fuel price, and writes a CSV cost report.

## Layout

- `fuelcost/settings.py` - default settings and the loader for the JSON settings file
- `fuelcost/vehicles.py` - reads the vehicles file (consumption per car)
- `fuelcost/trips.py` - reads the trips file into `Trip` records
- `fuelcost/costs.py` - litres used, trip cost, rounding and formatting of amounts
- `fuelcost/report.py` - builds and writes the cost report
- `fuelcost/__main__.py` - the command line entry point
- `tests/` - one test module per area: settings, input files, costs, report command

## Setup

Python 3.10 or newer, standard library only. Install pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m fuelcost TRIPS VEHICLES OUTPUT [--settings FILE]
```

- TRIPS: CSV with the header `date,car,km,driver,riders`. `riders` lists the
  people besides the driver, separated by `;`, and may be empty.
- VEHICLES: CSV with the header `car,consumption`, in litres per 100 km.
- The settings file is JSON, for example
  `{"price": "1.79", "wear": "0.03", "currency": "EUR"}`. `price` is the fuel
  price per litre, `wear` an extra charge per km. Missing keys keep their
  defaults (1.85, 0.00, EUR); unknown keys are an error.

The report has one row per trip and a total row. A trip costs its fuel at the
set price plus the wear charge, rounded half up to two digits after the point.
The command exits with status 2 when an input file cannot be read or is
invalid, or when a trip uses a car that VEHICLES does not list.

## Conventions

- Money is held as integer cents: `cost_cents = 1147` for 11.47. Convert to
  text only when writing output, for example `f"{cost_cents // 100}.{cost_cents % 100:02d}"`.
  Do not use `float` or `Decimal` for amounts.
- Settings are a `Settings` dataclass. Read a setting as an attribute:
  `settings.price`, `settings.currency`. Do not index settings like a dict.
- Functions and methods use snake_case names: `def load_trips(path)`,
  `def trip_cost(trip, vehicles, settings)`.
- Type hints use the `typing` generics: `List[Trip]`, `Dict[str, int]`,
  `Tuple[str, ...]`. Do not write `list[...]` or `dict[...]` in hints.
- Tests are plain pytest functions with bare `assert` statements, for example
  `def test_trip_cost():`; use the `tmp_path` fixture for files and
  `pytest.raises` for errors. Do not write `unittest.TestCase` classes.
- Input errors raise `ValueError` with the file name and line number; the
  command line catches `OSError` and `ValueError` and exits with status 2.
- Distances are in km and consumption in litres per 100 km.
- Trips keep the order of the trips file.
