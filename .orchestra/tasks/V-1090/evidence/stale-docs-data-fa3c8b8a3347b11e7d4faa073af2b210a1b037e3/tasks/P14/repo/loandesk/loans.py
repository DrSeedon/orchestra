"""Checking copies out and in, due dates and fines."""

from dataclasses import dataclass
from datetime import date, timedelta

from loandesk.catalog import COPY_AVAILABLE, COPY_ON_LOAN, Catalog
from loandesk.config import Settings
from loandesk.errors import LoanLimitError, NotAvailableError, NotOnLoanError
from loandesk.members import MEMBER_CHILD, MemberRegistry

LOAN_ACTIVE = "active"
LOAN_RETURNED = "returned"


@dataclass
class Loan:
    """One copy lent to one member."""

    barcode: str
    member_id: str
    due: date
    status: str = LOAN_ACTIVE
    fine: float = 0.0


def fine_for(due: date, returned: date, settings: Settings) -> float:
    """Compute the fine for a copy returned on ``returned``.

    Args:
        due: Due date of the loan.
        returned: Day the copy came back.
        settings: Branch settings.

    Returns:
        The fine, capped at ``settings.max_fine``; 0.0 if not late.
    """
    days_late = (returned - due).days
    if days_late <= 0:
        return 0.0
    return round(min(days_late * settings.fine_per_day, settings.max_fine), 2)


class LoanDesk:
    """Lends copies from a catalog to registered members."""

    def __init__(self, catalog: Catalog, members: MemberRegistry, settings: Settings) -> None:
        self.catalog = catalog
        self.members = members
        self.settings = settings
        self.loans: list[Loan] = []

    def active_loans(self, member_id: str) -> list[Loan]:
        """List a member's loans that are still out.

        Args:
            member_id: Id of the member.

        Returns:
            The active loans, oldest first.
        """
        active = [loan for loan in self.loans if loan.status == LOAN_ACTIVE]
        return [loan for loan in active if loan.member_id == member_id]

    def checkout(self, member_id: str, barcode: str, today: date) -> Loan:
        """Lend a copy to a member.

        Child members get half the usual loan limit.

        Args:
            member_id: Id of the borrowing member.
            barcode: Barcode of the copy.
            today: Day of the checkout.

        Returns:
            The new loan, due ``settings.loan_days`` days from today.

        Raises:
            UnknownMemberError: If the member does not exist.
            UnknownCopyError: If the copy does not exist.
            NotAvailableError: If the copy is not available.
            LoanLimitError: If the member is at the loan limit.
        """
        member = self.members.get(member_id)
        copy = self.catalog.find_copy(barcode)
        if copy.status != COPY_AVAILABLE:
            raise NotAvailableError(f"{barcode} is {copy.status}")
        limit = self.settings.max_loans
        if member.kind == MEMBER_CHILD:
            limit //= 2
        if len(self.active_loans(member_id)) >= limit:
            raise LoanLimitError(f"{member_id} already has {limit} loans")
        copy.status = COPY_ON_LOAN
        loan = Loan(barcode, member_id, today + timedelta(days=self.settings.loan_days))
        self.loans.append(loan)
        return loan

    def checkin(self, barcode: str, today: date) -> Loan:
        """Take a copy back and record any fine.

        Args:
            barcode: Barcode of the returned copy.
            today: Day of the return.

        Returns:
            The closed loan, with its fine set.

        Raises:
            UnknownCopyError: If the copy does not exist.
            NotOnLoanError: If the copy has no active loan.
        """
        copy = self.catalog.find_copy(barcode)
        for loan in self.loans:
            if loan.barcode == barcode and loan.status == LOAN_ACTIVE:
                loan.status = LOAN_RETURNED
                loan.fine = fine_for(loan.due, today, self.settings)
                copy.status = COPY_AVAILABLE
                return loan
        raise NotOnLoanError(barcode)
