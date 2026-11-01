# gradebook

gradebook keeps the grades for a course. A course has students and weighted
assessments (homework, midterm, final, ...). The package records each
student's points, turns them into a weighted course percentage, maps that
percentage to a letter grade and builds the plain-text class report that
instructors send to the registrar.

## Layout

- `gradebook/models.py` - record types: `Student`, `Assessment`, `Score`
- `gradebook/weighting.py` - percentages and weighted averages
- `gradebook/letters.py` - letter grade scales and grade points
- `gradebook/course.py` - the `Course` class
- `gradebook/loader.py` - reads a course from its JSON export
- `gradebook/report.py` - report rows, class average, text table, report command
- `tests/` - pytest tests

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
python -m gradebook.report COURSE_JSON OUTPUT_TXT
```

writes the class report of a course export to a text file. A course export
is a JSON object with the keys `code`, `assessments` (`name`, `weight`,
`max`), `students` (`id`, `name`, `email` if known) and `scores` (`student`,
`assessment`, `points`; `null` points mean excused). The command exits with
status 2 when the export cannot be read.

## Conventions

- Standard library only.
- Every function and method in `gradebook/` is fully type-annotated, including
  return types.
- Records are dataclasses: declare them with `@dataclass` (use
  `@dataclass(frozen=True)` for values that never change) and typed fields.
- Function and method names use snake_case, for example `weighted_average`
  or `letter_for`.
- Write optional types as `X | None`, for example `float | None`. Do not
  import `Optional` from `typing`.
- An excused score has `points=None` and does not count toward the grade.
  Percentages are floats from 0 to 100; round them only when formatting.
- Test files live in `tests/` and are named `<module>_test.py`, for example
  `tests/weighting_test.py`.
- Keep functions short. A function does one job.
