"""Exceptions raised by loandesk."""


class LoanDeskError(Exception):
    """Base class for all loandesk errors."""


class ConfigError(LoanDeskError):
    """A settings line is malformed or names an unknown setting."""


class DataError(LoanDeskError):
    """A branch data file is missing, unreadable or malformed."""


class UnknownMemberError(LoanDeskError):
    """No member has the given member id."""


class UnknownCopyError(LoanDeskError):
    """No copy has the given barcode."""


class NotAvailableError(LoanDeskError):
    """The copy cannot be lent right now."""


class LoanLimitError(LoanDeskError):
    """The member already has the maximum number of loans."""


class NotOnLoanError(LoanDeskError):
    """The copy is not on loan, so it cannot be checked in."""
