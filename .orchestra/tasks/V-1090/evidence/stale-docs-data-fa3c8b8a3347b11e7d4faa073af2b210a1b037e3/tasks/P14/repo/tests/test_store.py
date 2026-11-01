from datetime import date

import pytest

from loandesk.catalog import COPY_AVAILABLE, COPY_ON_LOAN
from loandesk.errors import ConfigError, DataError, UnknownMemberError
from loandesk.loans import LOAN_ACTIVE
from loandesk.store import open_desk

MEMBERS = "member_id,name,kind\nM1,Ada Park,adult\nK1,Kim Lo,child\n"
COPIES = "barcode,title_id\nB1,dune\nB2,dune\nB9,emma\n"
LOANS = "barcode,member_id,due,status\nB1,M1,2026-03-23,active\nB9,K1,2026-02-01,returned\n"


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "members.csv").write_text(MEMBERS, encoding="utf-8")
    (tmp_path / "copies.csv").write_text(COPIES, encoding="utf-8")
    (tmp_path / "loans.csv").write_text(LOANS, encoding="utf-8")
    return tmp_path


def test_open_desk_loads_everything(data_dir):
    desk = open_desk(str(data_dir))
    assert desk.members.get("K1").name == "Kim Lo"
    assert [loan.due for loan in desk.loans] == [date(2026, 3, 23), date(2026, 2, 1)]
    assert [loan.barcode for loan in desk.active_loans("M1")] == ["B1"]
    assert desk.loans[0].status == LOAN_ACTIVE
    assert desk.catalog.find_copy("B1").status == COPY_ON_LOAN
    assert desk.catalog.find_copy("B9").status == COPY_AVAILABLE
    assert desk.settings.loan_days == 21


def test_settings_file_is_applied(data_dir):
    (data_dir / "settings.txt").write_text("# north\nmax_loans = 2\n", encoding="utf-8")
    desk = open_desk(str(data_dir))
    assert desk.settings.max_loans == 2
    (data_dir / "settings.txt").write_text("max_loans = two\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        open_desk(str(data_dir))


def test_missing_folder_and_file(data_dir):
    with pytest.raises(DataError):
        open_desk(str(data_dir / "nope"))
    (data_dir / "copies.csv").unlink()
    with pytest.raises(DataError):
        open_desk(str(data_dir))


@pytest.mark.parametrize(
    "loans",
    [
        "barcode,member_id,due\nB1,M1,2026-03-23\n",
        "barcode,member_id,due,status\nB1,M1,23.03.2026,active\n",
        "barcode,member_id,due,status\nB1,M1,2026-03-23,lent\n",
    ],
)
def test_bad_loans_file(data_dir, loans):
    (data_dir / "loans.csv").write_text(loans, encoding="utf-8")
    with pytest.raises(DataError):
        open_desk(str(data_dir))


def test_loan_of_unknown_member(data_dir):
    (data_dir / "loans.csv").write_text(LOANS + "B2,X9,2026-03-23,active\n", encoding="utf-8")
    with pytest.raises(UnknownMemberError):
        open_desk(str(data_dir))
