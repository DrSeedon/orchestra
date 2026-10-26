# recipebox

recipebox keeps recipes as small plain-text files, parses them, scales them to
a different number of servings and converts ingredient amounts between units.
It is used by the meal-planning scripts and has no runtime dependencies.

## Layout

- `recipebox/models.py` - recipe and ingredient records
- `recipebox/units.py` - unit tables and conversion to base units (g, ml, pc)
- `recipebox/parser.py` - parsing recipe text and reading recipe files
- `recipebox/scaling.py` - scaling recipes and formatting quantities for display
- `tests/` - pytest tests for the parser, the scaling helpers and the units

Recipe text format: a title line `# Pancakes (serves 4)`, then one ingredient
per line such as `200 g flour` or `2 eggs`. A line without a known unit, such
as `2 eggs`, is counted in pieces (`pc`).

## Setup

Python 3.10 or newer. Install pytest to run the tests; the package itself
needs nothing else.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. Tests that need files create them
under pytest's `tmp_path`.

## Conventions

- Value records (ingredients, recipes, anything that mainly holds data) are
  `typing.NamedTuple` classes, e.g. `class Ingredient(NamedTuple): ...`.
- Function and method names are lowerCamelCase, e.g. `scaleRecipe`,
  `toBaseUnit`. Variables and modules stay lowercase with underscores.
- Build strings with f-strings, e.g. `f"{amount} {unit} {name}"`.
- Type hints use the `typing` generics: `List[Ingredient]`,
  `Dict[str, float]`, `Tuple[float, str]`.
- Every function has type hints and a one-line docstring.
- Keep quantities as floats and round them only when formatting for display.
- Unknown units raise `ValueError` with the unit in the message.
- Standard library only.
