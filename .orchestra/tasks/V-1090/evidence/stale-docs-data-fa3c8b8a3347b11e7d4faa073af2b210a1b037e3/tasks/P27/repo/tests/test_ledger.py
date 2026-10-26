from datetime import date

import pytest

from rentroll.ledger import EntryKind, LedgerEntry, balances, load_ledger, signed_amount


def test_load_ledger(sample_files):
    entries = load_ledger(sample_files[1])
    assert len(entries) == 7
    assert entries[0] == LedgerEntry(day=date(2026, 9, 1), unit="1A", kind=EntryKind.CHARGE,
                                     amount=125050)
    assert entries[-1].kind is EntryKind.CREDIT


def test_signed_amount():
    charge = LedgerEntry(day=date(2026, 9, 1), unit="1A", kind=EntryKind.CHARGE, amount=500)
    credit = LedgerEntry(day=date(2026, 9, 1), unit="1A", kind=EntryKind.CREDIT, amount=200)
    assert signed_amount(charge) == 500
    assert signed_amount(credit) == -200


def test_balances(sample_files):
    assert balances(load_ledger(sample_files[1])) == {"1A": 0, "1B": 48000, "2A": -4000}


def test_unknown_kind(write_file):
    path = write_file("l.csv", "date,unit,kind,amount\n2026-09-01,1A,refund,10\n")
    with pytest.raises(ValueError, match="line 2"):
        load_ledger(path)


def test_amount_must_be_positive(write_file):
    path = write_file("l.csv", "date,unit,kind,amount\n2026-09-01,1A,payment,-10\n")
    with pytest.raises(ValueError, match="above zero"):
        load_ledger(path)
