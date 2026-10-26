# cartkit

cartkit computes shopping cart totals for the web shop. It loads the product
catalog from CSV, holds the customer's cart, and works out sales tax, shipping
and the printed receipt. It is a plain Python package with no runtime
dependencies and is used by the shop backend.

## Layout

- `cartkit/money.py` - parsing and formatting of money amounts
- `cartkit/catalog.py` - products and the CSV catalog loader
- `cartkit/cart.py` - the cart and its lines
- `cartkit/checkout.py` - tax, shipping and receipts
- `cartkit/errors.py` - the `CartError` types raised by the catalog and the cart
- `tests/` - unit tests, one test module per source module, shared fixtures in `conftest.py`

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. All tests must pass before you push.

## Conventions

- Money amounts are `decimal.Decimal` values. Build them from strings
  (`Decimal("4.99")`), never from floats, and quantize to two places with
  `ROUND_HALF_UP` when a value is shown or stored.
- Report bad input by raising a built-in exception: `ValueError` for invalid
  values, `KeyError` for unknown keys such as SKUs, codes or regions.
- Build strings with f-strings, e.g. `f"{name}: {amount}"`.
- Test files are named `test_<module>.py`, e.g. `tests/test_cart.py`.
- Standard library only; do not add third-party packages.
- Keep lines under 100 characters.
- Every public function and method has a one-line docstring.
- Tests write files only under pytest's `tmp_path`.
