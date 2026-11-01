"""Records and the error type shared by the hostsfile modules."""
from dataclasses import dataclass, field
from enum import Enum


class HostsFileError(Exception):
    """A hosts file or an edit request is not valid."""


class LineKind(Enum):
    """What one line of a hosts file holds."""

    BLANK = "blank"
    COMMENT = "comment"
    ENTRY = "entry"


class Family(Enum):
    """The address family of an entry."""

    IPV4 = 4
    IPV6 = 6


@dataclass
class HostLine:
    """One line of a hosts file.

    Attributes:
        number: The line number, starting at 1.
        kind: What the line holds.
        address: The address of an entry line, empty for other lines.
        names: The host names of an entry line, in file order.
        comment: The comment text without the leading "#".
    """

    number: int
    kind: LineKind
    address: str = ""
    names: list[str] = field(default_factory=list)
    comment: str = ""

    @property
    def is_entry(self) -> bool:
        """True for a line that maps an address to host names."""
        return self.kind is LineKind.ENTRY
