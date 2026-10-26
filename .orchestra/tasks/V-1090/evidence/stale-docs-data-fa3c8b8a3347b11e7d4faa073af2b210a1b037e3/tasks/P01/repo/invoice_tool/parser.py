"""Read supplier invoice CSV files into raw row dictionaries."""
import csv
import os

REQUIRED_COLUMNS = ("invoice_no", "date", "amount", "currency")

COLUMN_ALIASES = {
    "invoice": "invoice_no",
    "invoice number": "invoice_no",
    "inv no": "invoice_no",
    "invoice date": "date",
    "total": "amount",
    "amount due": "amount",
    "ccy": "currency",
}


def canonical_column(name: str) -> str:
    """Map a supplier column header to our column name."""
    key = name.strip().lower()
    return COLUMN_ALIASES.get(key, key.replace(" ", "_"))


def read_invoice_csv(path: str, delimiter: str = ",") -> list[dict[str, str]]:
    """Read one supplier file and return its rows keyed by canonical column."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"invoice file not found: {path}")
    name = os.path.basename(path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{name}: file is empty") from None
        columns = [canonical_column(col) for col in header]
        missing = [col for col in REQUIRED_COLUMNS if col not in columns]
        if missing:
            raise ValueError(f"{name}: missing columns {', '.join(missing)}")
        rows = []
        for line_no, values in enumerate(reader, start=2):
            if not any(value.strip() for value in values):
                continue
            if len(values) != len(columns):
                print(f"{name}:{line_no}: expected {len(columns)} fields, "
                      f"got {len(values)}; row skipped")
                continue
            rows.append(dict(zip(columns, (value.strip() for value in values))))
    return rows
