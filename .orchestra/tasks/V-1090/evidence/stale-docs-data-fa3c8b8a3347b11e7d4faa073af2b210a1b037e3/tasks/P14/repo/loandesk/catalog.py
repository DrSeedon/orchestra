"""Copies of titles held by the branch."""

from dataclasses import dataclass

from loandesk.errors import UnknownCopyError

COPY_AVAILABLE = "available"
COPY_ON_LOAN = "on_loan"
COPY_LOST = "lost"


@dataclass
class Copy:
    """One physical copy of a title."""

    barcode: str
    title_id: str
    status: str = COPY_AVAILABLE


class Catalog:
    """All copies held by the branch, by barcode."""

    def __init__(self) -> None:
        self._copies: dict[str, Copy] = {}

    def add_copy(self, barcode: str, title_id: str) -> Copy:
        """Register a new copy as available.

        Args:
            barcode: Barcode printed on the copy.
            title_id: Id of the title the copy belongs to.

        Returns:
            The new copy.
        """
        copy = Copy(barcode, title_id)
        self._copies[barcode] = copy
        return copy

    def find_copy(self, barcode: str) -> Copy:
        """Look up a copy.

        Args:
            barcode: Barcode of the copy.

        Returns:
            The copy.

        Raises:
            UnknownCopyError: If no copy has this barcode.
        """
        try:
            return self._copies[barcode]
        except KeyError:
            raise UnknownCopyError(barcode) from None

    def copies_of(self, title_id: str) -> list[Copy]:
        """List the copies of a title, ordered by barcode.

        Args:
            title_id: Id of the title.

        Returns:
            The copies, possibly empty.
        """
        return sorted(
            (c for c in self._copies.values() if c.title_id == title_id),
            key=lambda c: c.barcode,
        )

    def available_copies(self, title_id: str) -> list[Copy]:
        """List the copies of a title that can be lent now.

        Args:
            title_id: Id of the title.

        Returns:
            The available copies, ordered by barcode.
        """
        return [c for c in self.copies_of(title_id) if c.status == COPY_AVAILABLE]
