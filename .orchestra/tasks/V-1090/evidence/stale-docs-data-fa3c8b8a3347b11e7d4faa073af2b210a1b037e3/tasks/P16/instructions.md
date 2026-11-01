# budgetbook

budgetbook keeps our household books in a plain CSV ledger and compares the
spending of each month with a budget per category. It reads the ledger and the
budget file, nets refunds against expenses, and writes a small CSV report that
we look at at the end of every month.

## Layout

- `budgetbook/money.py` - parses, formats and adds money amounts
- `budgetbook/ledger.py` - reads the ledger CSV into transactions, selects a month
- `budgetbook/budgets.py` - reads the budget file (category,limit)
- `budgetbook/summary.py` - spending per category and income totals
- `budgetbook/report.py` - the monthly report command
- `tests/` - tests, one file per module (summary is covered with budgets)

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run it from the repository root.

## Usage

```
python -m budgetbook.report LEDGER MONTH OUTPUT [--budgets FILE]
```

MONTH is written as `YYYY-MM`. The ledger has the columns
date,category,kind,amount,note; kind is expense, refund or income.

## Conventions

- Standard library only.
- Money is handled as integer cents. Convert amounts to an `int` number of
  cents when you read them (`amount_cents = 1250` for 12.50) and do all
  arithmetic on those integers. Do not use `Decimal` or floats for money.
- Model a fixed set of named values as an `enum.Enum`, for example
  `class Kind(Enum): EXPENSE = "expense"`. Do not define module-level string
  constants for such values.
- Name functions, methods and variables in snake_case, for example
  `def spent_in_month(...)`. Do not use camelCase names.
- Test files live in `tests/` and are named `<module>_test.py`, for example
  `tests/ledger_test.py`.
- Write a value that may be missing as `Optional[X]` from `typing`, for
  example `note: Optional[str] = None`. Do not use the `X | None` form.
- Category names are compared in lower case.
- Command-line tools write their result to the output file given on the
  command line. On bad input they write an error message to stderr and exit
  with status 2.
