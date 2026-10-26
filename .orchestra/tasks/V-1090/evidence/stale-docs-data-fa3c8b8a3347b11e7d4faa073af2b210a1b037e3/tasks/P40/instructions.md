# couponkit

couponkit works out the total of a web shop cart and the discount that a
coupon gives on it. It reads a cart file and a coupon file and shows the
subtotal, the discount and the total. The package has no third-party
dependencies.

## Layout

- `couponkit/settings.py` - the settings, their defaults and the settings file reader
- `couponkit/money.py` - parses, rounds and formats money amounts
- `couponkit/cart.py` - the `CartLine` record, reading the cart file, the cart subtotal
- `couponkit/coupons.py` - the `Coupon` record, reading the coupon file, the discount of one coupon
- `couponkit/cli.py` - the command line
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
python -m couponkit.cli --settings shop.json cart.csv
python -m couponkit.cli --settings shop.json cart.csv --coupon SAVE10
```

The settings file is a JSON object. The known settings are `coupons_file`
(default `coupons.json`) and `currency` (default `EUR`). An unknown setting,
or a value that is not of the type of its default, is an error.

The cart file is a CSV file with the header `sku,quantity,price`. The
quantity is a whole number above zero, and the price of one item has at most
two digits after the point.

The coupon file is JSON: `{"coupons": [{"code": "SAVE10", "kind": "percent",
"value": "10"}, {"code": "FIVE", "kind": "amount", "value": "5.00",
"minimum": "20.00"}]}`. A coupon gives nothing when the subtotal is below its
minimum. Coupon codes are not case-sensitive. Commands write a message to
stderr and exit with status 2 when an input cannot be read.

## Conventions

- Money is an integer number of cents, for example `1230` for 12.30. Name
  such values with a `_cents` suffix, for example `price_cents`. Do not use
  floats or `Decimal` for money.
- Settings are a `Settings` dataclass with one field per setting. Read a
  setting as an attribute, for example `settings.coupons_file`. A new setting
  is a new field with a default in `couponkit/settings.py`.
- Signal bad input with built-in exceptions: `ValueError` for a bad value and
  `KeyError` for a name that is not known. Do not define exception classes of
  your own.
- Test files live in `tests/` and are named `<module>_test.py`, for example
  `tests/cart_test.py`.
- Standard library only. Read CSV files with the `csv` module and JSON files
  with the `json` module.
- Percent discounts are rounded to the cent, halves up. Amounts in output
  always have two digits after the point (`12.30`).
