# payrun

payrun computes weekly pay for our hourly staff. It reads the employee
registry, works out gross pay from hours worked (with overtime above 40
hours), applies income tax bands and pension contributions, and writes a
text payslip per employee. Finance runs it every Friday.

## Layout

- `payrun/money.py` - parsing, rounding and formatting of amounts
- `payrun/employees.py` - `Employee` records and the employee registry file
- `payrun/deductions.py` - income tax bands and pension contributions
- `payrun/payslip.py` - gross pay, the `Payslip` record and payslip text
- `payrun/__main__.py` - the weekly pay run command
- `tests/` - pytest tests, one file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m payrun REGISTRY HOURS OUTPUT
```

REGISTRY has one `id,name,hourly rate,pension rate` line per employee, for
example `E01,Ana Silva,18.50,0.05`. HOURS has one `id,hours` line per
employee. In both files blank lines and lines starting with `#` are skipped.
The payslips go to OUTPUT in the order of HOURS. The command exits with
status 2 and writes nothing if an input file is missing or has a bad line.

## Conventions

- Standard library only; no third-party packages at runtime.
- Money is an `int` number of cents. Every variable, field, parameter and
  constant that holds money ends in `_cents` (`gross_cents`, `tax_cents`,
  `cap_cents`). Never use `float` for money. Convert to a display string
  only at the edge (payslip text).
- Functions that can fail on bad input do not raise. They return a pair
  `(value, error)`: `(result, None)` on success and `(None, "reason")` on
  failure. The caller checks the error before using the value.
- Function and method names are `snake_case`
  (for example `compute_overtime`, `load_lines`).
- Inside the package, import sibling modules with relative imports:
  `from .money import ...`, `from .employees import ...`.
- Tax bands and overtime rules live in one place each (`deductions.py` and
  `payslip.py`); do not copy the numbers into other modules.
- Tests never read real payroll files. They pass lists of lines, or write
  small input files under pytest's `tmp_path`.
- Line length is 100 characters.
