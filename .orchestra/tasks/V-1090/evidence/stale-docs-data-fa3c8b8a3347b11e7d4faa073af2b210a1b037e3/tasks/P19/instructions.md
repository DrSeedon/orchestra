# shiprate

shiprate prices outgoing parcels for the warehouse. Each destination
country belongs to a shipping zone, and each zone has rate bands by weight.
The quote command looks up the band of every parcel, adds the fuel surcharge
and writes one CSV row per parcel for the carrier booking.

## Layout

- `shiprate/settings.py` - default settings and the loader for the JSON settings file
- `shiprate/money.py` - parsing, formatting and percentages of money amounts
- `shiprate/csvfiles.py` - reading CSV input files with required columns
- `shiprate/zones.py` - the zone table (`zones.csv`) and zone lookup per country
- `shiprate/rates.py` - the rate table (`rates.csv`) and the price of a parcel per zone and weight
- `shiprate/parcels.py` - the parcel list
- `shiprate/quote.py` - the quote command
- `tests/` - pytest tests; zones, rates and parcels are covered in `tests/test_tables.py`

## Setup

Python 3.10 or newer. Only the standard library is used; install pytest to
run the tests.

## Running tests

```
python -m pytest -q
```

## Usage

```
python -m shiprate.quote DATA_DIR PARCELS OUTPUT [--settings FILE]
```

DATA_DIR holds `zones.csv` (country,zone) and `rates.csv`
(zone,max_grams,price). PARCELS is a CSV file with the columns
id,country,grams. The settings file is JSON; keys that are left out keep
their defaults (`currency` "EUR", `fuel_percent` 8, `max_weight_grams` 31500).

## Conventions

- Standard library only.
- Hold money as `decimal.Decimal`, for example `Decimal("4.90")`, and round
  with `amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. Do not
  keep amounts as integer cents.
- Settings are a plain dict keyed by setting name. Read them with
  `settings["fuel_percent"]` or `settings.get("currency")`. Do not read
  settings as attributes.
- Build messages with `str.format()`, for example
  `"no rate for {} g in zone {}".format(grams, zone)`. Do not use f-strings.
- Write docstrings with reST fields, for example
  `:param grams: weight of the parcel in grams` and `:returns: the price`.
  Do not write `Args:` or `Returns:` sections.
- Raise the package's own exception classes, all derived from one
  `ShipRateError` base class, for example `raise UnknownZoneError(zone)`.
  Do not raise `ValueError` or `KeyError` from the package.
- Country codes and zone names are upper case after loading.
- Percentages are whole numbers; a share of an amount is rounded half up.
- Command-line tools exit with status 2 on bad input and write the reason
  to stderr.
