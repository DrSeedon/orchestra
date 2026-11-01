# tipjar

tipjar settles restaurant bills for our team lunches. It reads the bill that
the organiser types into a CSV file, adds the tip and works out how much each
person pays. The result is a short text summary that goes into the lunch
channel.

## Layout

- `tipjar/money.py` - parses, rounds and formats money amounts
- `tipjar/bill.py` - reads the bill file and adds up its items
- `tipjar/tips.py` - parses tip percentages and computes the tip and the total
- `tipjar/split.py` - splits an amount evenly between people
- `tipjar/summary.py` - the summary command: bill, tip, total and one line per person
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m tipjar.summary BILL_CSV PEOPLE OUTPUT_TXT [--tip PERCENT]
```

The bill file has the header `item,amount`, with amounts such as `12.50`.
`--tip` takes a whole percentage such as `15` or `15%`; without it the summary
has no tip line. The command exits with status 2 when the bill or the tip is
invalid.

## Conventions

- Keep money as integer cents (`int`) inside the package: `1230` is 12.30.
  Convert from and to the `12.30` text form only when reading input and
  writing output. Never use `float` for money.
- Report invalid input by returning a `(value, error)` pair: `(result, None)`
  on success, `(None, "message")` on failure. Callers check the error first.
  The command's `main()` writes the message to stderr and returns 2.
- Build text with f-strings, for example `f"{name:<20} {amount:>10}"`.
- Write a hint for a value that can be missing as `Optional[X]` from
  `typing`, for example `tip: Optional[int] = None`.
- Inside the package, use absolute imports:
  `from tipjar.money import parse_amount`.
- Standard library only. pytest is the only development dependency.
- Tips are rounded half up to 0.01. When an amount is split, each share is
  rounded down and the hundredths left over go one at a time to the first
  people, so the shares always add up to the amount.
- Type hints on public functions use built-in generics such as
  `list[BillItem]`.
- Tests are plain pytest functions in `tests/test_<module>.py`. They write
  files only under pytest's `tmp_path`.
