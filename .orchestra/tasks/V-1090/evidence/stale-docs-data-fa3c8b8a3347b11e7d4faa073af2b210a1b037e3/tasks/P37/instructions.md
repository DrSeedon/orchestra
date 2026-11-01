# pricewatch

pricewatch reads the price lists that our suppliers send and gives quick
summaries of them on the terminal. A price list is a CSV file with one row
per product. The package has no third-party dependencies.

## Layout

- `pricewatch/money.py` - parses and formats money amounts
- `pricewatch/pricelist.py` - the `PriceItem` record, reading and writing price list files
- `pricewatch/report.py` - summaries of one price list: cheapest items, price range, average price
- `pricewatch/cli.py` - the command line (`summary`, `cheapest`)
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
python -m pricewatch.cli summary prices.csv
python -m pricewatch.cli cheapest prices.csv --count 3
```

A price list has the header `sku,name,price`. A price has at most two digits
after the point and must be above zero, and a sku may appear only once.
Commands write a message to stderr and exit with status 2 when a file cannot
be read.

## Conventions

- Money is `decimal.Decimal`. Build amounts from strings, for example
  `Decimal("12.30")`, and round with `.quantize(Decimal("0.01"))`. Never use
  binary floating point numbers for money.
- Functions that can fail on bad input do not raise. They return a pair
  `(value, error)`: `(result, None)` on success and `(None, "what is wrong")`
  on failure, for example `return None, f"bad price: {text}"`. The caller
  checks the error first.
- Build text with f-strings, for example `f"{sku}: {price}"`. Do not use
  `str.format()` or `%` formatting.
- Test files are named `test_<module>.py`, for example `tests/test_money.py`.
- Function and method names are snake_case, for example `load_price_list()`
  and `format_item()`. Class names are CapWords.
- Standard library only. Read and write CSV files with the `csv` module.
- Amounts in output always have two digits after the point (`12.30`).
