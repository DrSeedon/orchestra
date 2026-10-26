"""Read and write the files of a fund folder.

A fund folder holds three files:

- ``fund.txt`` with ``name = ...`` and ``budget = 5000.00`` lines
- ``awards.csv`` with the columns date, recipient, amount (may be missing)
- ``applications.csv`` with the columns applicant, requested
"""
import csv
import os
from datetime import date

from grantpot.models import Application, Award, Fund
from grantpot.money import format_cents, parse_cents

FUND_FILE = "fund.txt"
AWARDS_FILE = "awards.csv"
APPLICATIONS_FILE = "applications.csv"
AWARD_COLUMNS = ["date", "recipient", "amount"]


def read_key_values(path: str) -> dict[str, str]:
    """Read ``key = value`` lines; blank lines and ``#`` comments are skipped."""
    values = {}
    with open(path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                raise ValueError(f"{os.path.basename(path)} line {number}: expected key = value")
            values[key.strip()] = value.strip()
    return values


def load_fund(folder: str) -> Fund:
    """Load the name and the budget of the fund in ``folder``."""
    values = read_key_values(os.path.join(folder, FUND_FILE))
    for key in ("name", "budget"):
        if key not in values:
            raise ValueError(f"{FUND_FILE}: no {key}")
    return Fund(values["name"], parse_cents(values["budget"]))


def load_awards(folder: str) -> list[Award]:
    """Load the awards paid so far, in file order; none when the file is missing."""
    path = os.path.join(folder, AWARDS_FILE)
    if not os.path.exists(path):
        return []
    awards = []
    with open(path, newline="", encoding="utf-8") as fh:
        for number, row in enumerate(csv.DictReader(fh), start=2):
            try:
                day = date.fromisoformat(row["date"])
                amount_cents = parse_cents(row["amount"])
            except ValueError as err:
                raise ValueError(f"{AWARDS_FILE} line {number}: {err}") from None
            awards.append(Award(day, row["recipient"].strip(), amount_cents))
    return awards


def load_applications(folder: str) -> list[Application]:
    """Load the pending applications, in file order."""
    applications = []
    path = os.path.join(folder, APPLICATIONS_FILE)
    with open(path, newline="", encoding="utf-8") as fh:
        for number, row in enumerate(csv.DictReader(fh), start=2):
            try:
                requested_cents = parse_cents(row["requested"])
            except ValueError as err:
                raise ValueError(f"{APPLICATIONS_FILE} line {number}: {err}") from None
            applications.append(Application(row["applicant"].strip(), requested_cents))
    return applications


def append_award(folder: str, award: Award) -> None:
    """Add one award to ``awards.csv``; the file is created with a header if needed."""
    path = os.path.join(folder, AWARDS_FILE)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(AWARD_COLUMNS)
        writer.writerow([award.day.isoformat(), award.recipient, format_cents(award.amount)])
