"""Library members."""

from dataclasses import dataclass

from loandesk.errors import UnknownMemberError

MEMBER_ADULT = "adult"
MEMBER_CHILD = "child"


@dataclass(frozen=True)
class Member:
    """A registered library member."""

    member_id: str
    name: str
    kind: str = MEMBER_ADULT


class MemberRegistry:
    """Members of the branch, by member id."""

    def __init__(self) -> None:
        self._members: dict[str, Member] = {}

    def add(self, member: Member) -> None:
        """Add or replace a member.

        Args:
            member: The member to store.
        """
        self._members[member.member_id] = member

    def get(self, member_id: str) -> Member:
        """Look up a member.

        Args:
            member_id: Id on the library card.

        Returns:
            The member.

        Raises:
            UnknownMemberError: If no member has this id.
        """
        try:
            return self._members[member_id]
        except KeyError:
            raise UnknownMemberError(member_id) from None
