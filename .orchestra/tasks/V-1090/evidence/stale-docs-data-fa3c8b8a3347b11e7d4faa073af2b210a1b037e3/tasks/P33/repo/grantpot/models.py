"""Records of a grants fund. Every money field holds whole cents."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fund:
    """A grants fund: its name and its total budget."""

    name: str
    budget: int


@dataclass(frozen=True)
class Award:
    """A grant that the fund has paid out."""

    day: date
    recipient: str
    amount: int


@dataclass(frozen=True)
class Application:
    """A pending request for money from the fund."""

    applicant: str
    requested: int
