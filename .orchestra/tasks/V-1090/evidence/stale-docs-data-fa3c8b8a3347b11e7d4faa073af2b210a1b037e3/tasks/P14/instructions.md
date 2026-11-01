# loandesk

loandesk runs the lending desk of a branch library. It keeps the catalog of
physical copies, the member registry and the loans: checkout with due dates
and loan limits, check-in with late fines. Branch staff use it through the
desk terminal, which calls this package directly.

## Layout

- `loandesk/config.py` - branch settings (loan period, fines, loan limit)
- `loandesk/catalog.py` - copies of titles and their availability
- `loandesk/members.py` - members and the member registry
- `loandesk/loans.py` - `LoanDesk`: checkout, check-in, fines
- `loandesk/store.py` - loads a desk from a branch data folder
- `loandesk/errors.py` - error types
- `tests/` - pytest tests, one file per area

Each branch keeps its data in one folder: `members.csv` (member_id, name,
kind), `copies.csv` (barcode, title_id), `loans.csv` (barcode, member_id,
due, status) and `settings.txt` with `name = value` lines. When a branch has
no `settings.txt`, the default settings apply.

## Setup

Python 3.10 or newer. The package needs nothing outside the standard
library. Install pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Conventions

- Standard library only.
- Fixed sets of values (copy status, loan status, member kind) are `Enum`
  classes, for example `class LoanStatus(str, Enum)` with members
  `ACTIVE = "active"` and `RETURNED = "returned"`. Compare against the
  members, not against bare strings.
- Settings are a plain `dict` returned by `config.load_settings()`. Read
  them by key, e.g. `settings["loan_days"]`. A new setting is a new key with
  its default in `load_settings()`.
- Signal errors with built-in exceptions: `KeyError` for an unknown id,
  `ValueError` for a bad argument, `RuntimeError` for an action that is not
  allowed in the current state. Do not add project-specific exception
  classes.
- Every public function and method has a reStructuredText docstring with
  `:param name:`, `:returns:` and `:raises SomeError:` fields.
- Dates are `datetime.date` values passed in by the caller (`today`); code
  never calls `date.today()` itself, so tests stay deterministic.
- Tests use pytest fixtures. Tests that need a data folder build one under
  `tmp_path`; no test uses the network.
- Line length is 100 characters.
