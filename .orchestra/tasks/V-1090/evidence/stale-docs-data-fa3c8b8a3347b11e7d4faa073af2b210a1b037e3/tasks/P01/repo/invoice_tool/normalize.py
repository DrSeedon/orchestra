"""Turn raw invoice rows into normalized invoice records."""
from datetime import datetime

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y%m%d")
KNOWN_CURRENCIES = {"EUR", "USD", "GBP", "CHF"}


def parse_date(text: str) -> str:
    """Return the date as an ISO string (YYYY-MM-DD)."""
    cleaned = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {text!r}")


def parse_amount(text: str) -> int:
    """Return the amount in integer cents ('1,234.50', '12,5' and '-3.10' are accepted)."""
    cleaned = text.strip().replace(" ", "")
    if not cleaned:
        raise ValueError("empty amount")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"bad amount: {text!r}") from None
    return round(value * 100)


def normalize_row(row: dict[str, str], supplier: str) -> dict:
    """Build one normalized invoice record from a raw row."""
    currency = row["currency"].strip().upper()
    if currency not in KNOWN_CURRENCIES:
        raise ValueError(f"unknown currency: {currency!r}")
    invoice_no = row["invoice_no"].strip().upper()
    if not invoice_no:
        raise ValueError("missing invoice number")
    return {
        "supplier": supplier,
        "invoice_no": invoice_no,
        "date": parse_date(row["date"]),
        "amount_cents": parse_amount(row["amount"]),
        "currency": currency,
    }


def normalize_rows(rows: list[dict[str, str]], supplier: str) -> list[dict]:
    """Normalize all rows of one supplier file, skipping rows that do not parse."""
    records = []
    for index, row in enumerate(rows, start=1):
        try:
            records.append(normalize_row(row, supplier))
        except (KeyError, ValueError) as exc:
            print(f"{supplier}: row {index} skipped: {exc}")
    return records
