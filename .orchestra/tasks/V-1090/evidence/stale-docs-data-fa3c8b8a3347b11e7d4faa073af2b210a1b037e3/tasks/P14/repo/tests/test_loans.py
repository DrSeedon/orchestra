from datetime import date

import pytest

from loandesk.catalog import COPY_AVAILABLE, COPY_ON_LOAN, Catalog
from loandesk.config import Settings
from loandesk.errors import (
    LoanLimitError,
    NotAvailableError,
    NotOnLoanError,
    UnknownCopyError,
    UnknownMemberError,
)
from loandesk.loans import LOAN_RETURNED, LoanDesk, fine_for
from loandesk.members import MEMBER_CHILD, Member, MemberRegistry

DAY = date(2026, 3, 2)


@pytest.fixture
def desk():
    catalog = Catalog()
    for n in range(1, 5):
        catalog.add_copy(f"B{n}", "dune")
    catalog.add_copy("B9", "emma")
    members = MemberRegistry()
    members.add(Member("M1", "Ada"))
    members.add(Member("K1", "Kim", MEMBER_CHILD))
    return LoanDesk(catalog, members, Settings(max_loans=4))


def test_checkout_sets_due_date_and_status(desk):
    loan = desk.checkout("M1", "B1", DAY)
    assert loan.due == date(2026, 3, 23)
    assert desk.catalog.find_copy("B1").status == COPY_ON_LOAN
    assert [c.barcode for c in desk.catalog.available_copies("dune")] == ["B2", "B3", "B4"]


def test_checkout_errors(desk):
    desk.checkout("M1", "B1", DAY)
    with pytest.raises(NotAvailableError):
        desk.checkout("M1", "B1", DAY)
    with pytest.raises(UnknownMemberError):
        desk.checkout("X", "B2", DAY)
    with pytest.raises(UnknownCopyError):
        desk.checkout("M1", "nope", DAY)


def test_child_limit_is_half(desk):
    desk.checkout("K1", "B1", DAY)
    desk.checkout("K1", "B2", DAY)
    with pytest.raises(LoanLimitError):
        desk.checkout("K1", "B3", DAY)


def test_checkin_records_fine(desk):
    desk.checkout("M1", "B9", DAY)
    loan = desk.checkin("B9", date(2026, 3, 27))
    assert loan.status == LOAN_RETURNED
    assert loan.fine == 1.0
    assert desk.catalog.find_copy("B9").status == COPY_AVAILABLE
    with pytest.raises(NotOnLoanError):
        desk.checkin("B9", DAY)


def test_fine_is_capped():
    settings = Settings()
    assert fine_for(DAY, DAY, settings) == 0.0
    assert fine_for(DAY, date(2026, 6, 1), settings) == settings.max_fine
