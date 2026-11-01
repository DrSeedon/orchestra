# rentroll

rentroll keeps track of what the tenants of our rental units owe. It reads the
tenants file and the ledger of charges, payments and credits, and writes the
monthly rent roll as a CSV file. The property office uses the rent roll to
follow up on open balances.

## Layout

- `rentroll/money.py` - parses amounts from the input files and formats amounts for output
- `rentroll/tenants.py` - reads the tenants file (unit, name, monthly rent, start date)
- `rentroll/ledger.py` - reads the ledger and sums the balance of each unit
- `rentroll/report.py` - builds the rent roll lines and writes them as CSV
- `rentroll/__main__.py` - the command line entry point
- `tests/` - tests, one file per module, shared fixtures and sample files in `conftest.py`

## Setup

Python 3.10 or newer. The package uses the standard library only; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m rentroll TENANTS LEDGER OUTPUT [--sort unit|balance]
```

- TENANTS is a CSV file with the columns `unit,name,rent,since`.
- LEDGER is a CSV file with the columns `date,unit,kind,amount`. The kind is
  `charge`, `payment` or `credit`; amounts are always positive.
- Ledger lines of units without a tenant are left out of the rent roll and
  reported. The command exits with status 2 when an input file cannot be read.

## Conventions

- Hold money as `decimal.Decimal`, for example `Decimal("1250.50")`, and round
  with `amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. Never use
  float or plain integers for money amounts.
- Name a fixed set of values (kinds, statuses, sort orders) with module-level
  string constants, for example `CHARGE = "charge"` and `PAYMENT = "payment"`.
  Do not use `enum.Enum`.
- Signal errors with the package's own exception classes. They all derive from
  one base class, `RentrollError`, for example `raise UnknownUnitError(unit)`.
  Do not raise built-in exceptions such as `ValueError`.
- Test files live in `tests/` and are named `<module>_test.py`, for example
  `tests/ledger_test.py`.
- Annotate collections with the built-in generic types: `list[Tenant]`,
  `dict[str, int]`. Do not use `typing.List` or `typing.Dict`.
- Dates are ISO `YYYY-MM-DD` and are parsed with `date.fromisoformat`.
- Every public function has type hints and a docstring.
