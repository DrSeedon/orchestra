"""Loading a branch's lending desk from its data folder."""

import csv
import os
from datetime import date

from loandesk.catalog import COPY_ON_LOAN, Catalog
from loandesk.config import load_settings
from loandesk.errors import DataError
from loandesk.loans import LOAN_ACTIVE, LOAN_RETURNED, Loan, LoanDesk
from loandesk.members import Member, MemberRegistry


def _read_rows(data_dir: str, name: str, columns: list[str]) -> list[dict[str, str]]:
    path = os.path.join(data_dir, name)
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
    except OSError as exc:
        raise DataError(f"cannot read {path}: {exc.strerror}") from None
    missing = [column for column in columns if column not in (reader.fieldnames or [])]
    if missing:
        raise DataError(f"{path} has no column {missing[0]!r}")
    return rows


def open_desk(data_dir: str) -> LoanDesk:
    """Build the desk of a branch from its data folder.

    The folder holds ``members.csv`` (member_id, name, kind), ``copies.csv`` (barcode,
    title_id), ``loans.csv`` (barcode, member_id, due, status) and ``settings.txt`` with
    ``name = value`` lines. Without ``settings.txt`` the default settings apply.

    Args:
        data_dir: Path of the data folder.

    Returns:
        The desk with all members, copies and loans loaded.

    Raises:
        DataError: If a file is missing or unreadable, or a row is malformed.
        LoanDeskError: If a settings line is bad or a loan names an unknown member or copy.
    """
    settings_path = os.path.join(data_dir, "settings.txt")
    lines = None
    if os.path.isfile(settings_path):
        with open(settings_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    members = MemberRegistry()
    for row in _read_rows(data_dir, "members.csv", ["member_id", "name", "kind"]):
        members.add(Member(row["member_id"], row["name"], row["kind"]))
    catalog = Catalog()
    for row in _read_rows(data_dir, "copies.csv", ["barcode", "title_id"]):
        catalog.add_copy(row["barcode"], row["title_id"])
    desk = LoanDesk(catalog, members, load_settings(lines))
    for row in _read_rows(data_dir, "loans.csv", ["barcode", "member_id", "due", "status"]):
        if row["status"] not in (LOAN_ACTIVE, LOAN_RETURNED):
            raise DataError(f"loan of {row['barcode']} has unknown status {row['status']!r}")
        try:
            due = date.fromisoformat(row["due"])
        except ValueError:
            raise DataError(f"loan of {row['barcode']} has bad due date {row['due']!r}") from None
        members.get(row["member_id"])
        copy = catalog.find_copy(row["barcode"])
        if row["status"] == LOAN_ACTIVE:
            copy.status = COPY_ON_LOAN
        desk.loans.append(Loan(row["barcode"], row["member_id"], due, row["status"]))
    return desk
