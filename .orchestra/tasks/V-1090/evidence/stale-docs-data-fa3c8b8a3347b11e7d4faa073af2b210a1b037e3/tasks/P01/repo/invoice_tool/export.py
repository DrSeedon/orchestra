"""Write normalized invoice records to CSV."""
import csv
import os

FIELDS = ("supplier", "invoice_no", "date", "amount_cents", "currency")


def output_path(out_dir: str, name: str) -> str:
    """Return the CSV path used for an export called ``name``."""
    return os.path.join(out_dir, f"{name}.csv")


def write_records(records: list[dict], out_dir: str, name: str = "invoices") -> str:
    """Write records to <out_dir>/<name>.csv and return the file path."""
    if not records:
        raise ValueError("no records to write")
    os.makedirs(out_dir, exist_ok=True)
    target = output_path(out_dir, name)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record[field] for field in FIELDS})
    print(f"wrote {len(records)} records to {target}")
    return target
