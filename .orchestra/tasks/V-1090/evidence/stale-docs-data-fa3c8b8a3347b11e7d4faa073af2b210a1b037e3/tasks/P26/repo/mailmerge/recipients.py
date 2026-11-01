"""Read the recipients list of a mail merge from a CSV file."""
import csv
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def normalize_email(text: str) -> Optional[str]:
    """Return the address in lower case, or None if it does not look like an address."""
    email = text.strip().lower()
    if not ADDRESS.match(email):
        return None
    return email


def clean_columns(header: list[str]) -> list[str]:
    """Return the column names stripped and in lower case."""
    return [name.strip().lower() for name in header]


def load_recipients(path: Path) -> list[dict[str, str]]:
    """Read a recipients CSV file.

    The file needs an ``email`` column. Every column becomes a merge field.
    Rows with a bad address and repeats of an address seen before are skipped.
    """
    source = Path(path)
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{source.name}: file is empty")
        columns = clean_columns(header)
        if "email" not in columns:
            raise ValueError(f"{source.name}: no email column")
        for line_no, values in enumerate(reader, start=2):
            if not any(value.strip() for value in values):
                continue
            values = values + [""] * (len(columns) - len(values))
            row = {column: value.strip() for column, value in zip(columns, values)}
            email = normalize_email(row["email"])
            if email is None:
                logger.warning(f"{source.name}:{line_no}: bad address {row['email']!r}, row skipped")
                continue
            if email in seen:
                logger.warning(f"{source.name}:{line_no}: {email} is listed twice, row skipped")
                continue
            seen.add(email)
            row["email"] = email
            recipients.append(row)
    logger.info(f"read {len(recipients)} recipients from {source.name}")
    return recipients
