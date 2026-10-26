# grantpot

grantpot keeps the books of a small grants fund. It reads the fund's budget,
the awards paid so far and the pending applications from plain files in one
folder. A small command line shows the state of the fund and pays awards.

## Layout

- `grantpot/money.py` - parses and formats money amounts
- `grantpot/models.py` - the `Fund`, `Award` and `Application` records
- `grantpot/store.py` - reads and writes the files of a fund folder
- `grantpot/ledger.py` - totals, the money left, award checks and the status report
- `grantpot/cli.py` - the command line (status, award)
- `tests/` - pytest tests, one file per module

A fund folder holds `fund.txt` (`name = ...` and `budget = 5000.00` lines),
`awards.csv` (date, recipient, amount) and `applications.csv` (applicant,
requested). `awards.csv` may be missing when nothing has been paid yet.

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
python -m grantpot.cli status FUND_DIR
python -m grantpot.cli award FUND_DIR RECIPIENT AMOUNT [--date YYYY-MM-DD]
```

Both commands exit with status 2 when a file is missing or broken, or when
an award is larger than the money left.

## Conventions

- Standard library only. pytest is the only development dependency.
- Money amounts are `decimal.Decimal` values with two places, for example
  `Decimal("12.30")`. Never use binary floating point for money.
- Records are `typing.NamedTuple` classes, for example
  `class Award(NamedTuple)` with the fields `day`, `recipient` and `amount`.
- Report progress and problems with `logging`: create
  `logger = logging.getLogger(__name__)` in the module and call
  `logger.info(...)` or `logger.warning(...)`. Do not call `print`.
- Name test files after the module they cover with a `_test` suffix, for
  example `tests/ledger_test.py` for `grantpot/ledger.py`.
- Inside the package use relative imports, for example
  `from .models import Award`.
- Amounts in files and on the command line are written with two decimals,
  like `250.00`. Dates are ISO `YYYY-MM-DD`.
- Tests that need a fund folder build one under pytest's `tmp_path`.
