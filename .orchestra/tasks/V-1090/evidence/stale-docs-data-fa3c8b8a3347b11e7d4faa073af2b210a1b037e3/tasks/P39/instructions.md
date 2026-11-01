# sizechart

sizechart helps a small team shop pick clothing sizes. It reads a size chart
and a file with the body measurements of each person, and tells which size
fits whom. The package has no third-party dependencies.

## Layout

- `sizechart/units.py` - units of length (`cm`, `in`) and conversion to centimetres
- `sizechart/chart.py` - the measures, size ranges and sizes; reading the size chart file
- `sizechart/people.py` - the `Person` record and reading the people file
- `sizechart/recommend.py` - the smallest size of the chart that fits a person
- `sizechart/cli.py` - the command line
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
python -m sizechart.cli chart.csv people.csv
```

The size chart has the header `size,chest_min,chest_max,waist_min,waist_max,hip_min,hip_max`
with values in cm, one row per size from small to large. The people file has
the header `name,chest,waist,hip,unit`, where the unit is `cm` or `in`. A
range includes both of its ends. The command shows one line per person, such
as `Ana: M` or `Ana: no size`, and exits with status 2 when a file cannot be
read.

## Conventions

- Fixed sets of names, such as units and measures, are module-level string
  constants, for example `CHEST = "chest"`. Compare them with `==`. Do not
  use the `enum` module.
- Records are `typing.NamedTuple` classes with typed fields, for example
  `class Person(NamedTuple):`. Do not use `dataclasses`.
- Docstrings use reST field lists: one `:param name:` line per parameter
  and a `:returns:` line, for example `:param path: The file to read.`
- Modules inside the package import each other with relative imports, for
  example `from .chart import load_chart`.
- Tests are plain pytest functions with `assert`, for example
  `def test_load_chart(tmp_path):`. Use `pytest.raises` for errors. Do not
  write `unittest.TestCase` classes.
- Lengths inside the package are always centimetres. Measurements in inches
  are converted with `to_cm()` when a file is read.
- Read and write CSV files with the `csv` module. Readers raise `ValueError`
  with the line number, for example `line 3: bad chest value`.
