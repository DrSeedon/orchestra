"""The members of the club."""
from datetime import date
from typing import NamedTuple

from bookclub.csvfiles import parse_day, read_rows

COLUMNS = ("name", "email", "joined")


class Member(NamedTuple):
    """A club member.

    :param name: name of the member, unique in the club
    :param email: address for invitations
    :param joined: the day the member joined the club
    """

    name: str
    email: str
    joined: date


def load_members(path: str) -> list[Member]:
    """Read the member list of the club.

    :param path: path of ``members.csv``
    :returns: the members in file order
    :raises ValueError: if a row is invalid or a name is listed twice
    """
    members: list[Member] = []
    seen: set[str] = set()
    for line_no, row in read_rows(path, COLUMNS):
        where = "{}:{}".format(path, line_no)
        if not row["name"]:
            raise ValueError("{}: name is empty".format(where))
        if row["name"] in seen:
            raise ValueError("{}: member {} is listed twice".format(where, row["name"]))
        seen.add(row["name"])
        members.append(Member(row["name"], row["email"], parse_day(row["joined"], where)))
    return members


def members_on(members: list[Member], day: date) -> list[Member]:
    """Return the members who had joined the club by the given day.

    :param members: all members
    :param day: the day to check
    :returns: the members who joined on or before ``day``, sorted by name
    """
    return sorted((m for m in members if m.joined <= day), key=lambda m: m.name)
