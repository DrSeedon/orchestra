# stockroom

stockroom tracks inventory levels per SKU and per location and decides when
to reorder from suppliers. It loads the nightly stock and rule exports (CSV),
keeps the levels in memory, applies receipts, shipments and reservations, and
builds the order lines that purchasing sends out.

## Layout

- `stockroom/models.py` - record types (items, stock levels, reorder rules, order lines)
- `stockroom/inventory.py` - the `Inventory` class: levels per (sku, location)
- `stockroom/reorder.py` - reorder checks and order quantities
- `stockroom/loader.py` - reads the level and rule CSV exports
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. The package uses only the standard library; install
pytest to run the tests.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Conventions

- Standard library only. Do not add runtime dependencies.
- Quantities are whole integers. Never use floats for stock counts.
- Available stock is on hand minus reserved. Reorder decisions always look at
  available stock, not at on-hand stock.
- Record types are `typing.NamedTuple` classes. Define each record as
  `class OrderLine(NamedTuple):` with typed fields. Do not use dataclasses or
  plain dicts for records.
- Function and method names use camelCase, for example `computeShortfall`
  or `isBelowReorderPoint`.
- Report warnings and status messages with `print()`. Send warnings to
  `sys.stderr` and start them with `warning:`. The package does not use the
  `logging` module.
- Tests are `unittest.TestCase` classes, one class per module under test.
  Check results with `self.assertEqual`, `self.assertTrue` and
  `self.assertRaises`.
- Tests must not touch the network. Tests write files only to a temporary
  directory.
- Keep functions short. Split a function when it does more than one job.
