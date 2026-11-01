"""The meeting plan of the club."""
from datetime import date
from typing import NamedTuple

from bookclub.csvfiles import parse_day, read_rows

COLUMNS = ("day", "book_id", "host", "place")


class Meeting(NamedTuple):
    """A planned club meeting.

    :param day: the day of the meeting
    :param book_id: id of the book to discuss
    :param host: name of the member who hosts the meeting
    :param place: where the meeting takes place
    """

    day: date
    book_id: str
    host: str
    place: str


def load_meetings(path: str) -> list[Meeting]:
    """Read the meeting plan.

    :param path: path of ``meetings.csv``
    :returns: the meetings sorted by day
    :raises ValueError: if a row is invalid or two meetings share a day
    """
    meetings: list[Meeting] = []
    days: set[date] = set()
    for line_no, row in read_rows(path, COLUMNS):
        where = "{}:{}".format(path, line_no)
        day = parse_day(row["day"], where)
        if day in days:
            raise ValueError("{}: there is already a meeting on {}".format(where, day.isoformat()))
        days.add(day)
        meetings.append(Meeting(day, row["book_id"], row["host"], row["place"]))
    meetings.sort(key=lambda meeting: meeting.day)
    return meetings


def next_meeting(meetings: list[Meeting], day: date) -> Meeting | None:
    """Find the first meeting on or after a day.

    :param meetings: meetings sorted by day
    :param day: the day to start from
    :returns: the meeting, or None if no meeting is planned from that day on
    """
    for meeting in meetings:
        if meeting.day >= day:
            return meeting
    return None
