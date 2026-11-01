"""Command line: python -m bookclub.agenda CLUB_DIR DATE OUTPUT."""
import argparse
import sys
from datetime import date

from bookclub.club import Club, load_club
from bookclub.meetings import Meeting, next_meeting
from bookclub.members import members_on


def agenda_lines(club: Club, meeting: Meeting) -> list[str]:
    """Build the text of the agenda for one meeting.

    :param club: the club
    :param meeting: the meeting
    :returns: the lines of the agenda, without line ends
    """
    book = club.books[meeting.book_id]
    lines = [
        "Book club meeting on {}".format(meeting.day.isoformat()),
        "Place: {}".format(meeting.place),
        "Host: {}".format(meeting.host),
        "Book: {} ({} pages)".format(book.label(), book.pages),
        "",
        "Invited:",
    ]
    for member in members_on(club.members, meeting.day):
        lines.append("- {} <{}>".format(member.name, member.email))
    return lines


def main(argv: list[str] | None = None) -> int:
    """Write the agenda of the next meeting on or after DATE.

    :param argv: command line arguments without the program name
    :returns: the exit status
    """
    parser = argparse.ArgumentParser(prog="python -m bookclub.agenda")
    parser.add_argument("club_dir")
    parser.add_argument("date")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
    except ValueError:
        print("error: bad date {!r}".format(args.date), file=sys.stderr)
        return 2
    try:
        club = load_club(args.club_dir)
    except (OSError, ValueError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    meeting = next_meeting(club.meetings, day)
    if meeting is None:
        print("error: no meeting planned on or after {}".format(day.isoformat()), file=sys.stderr)
        return 2
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write("\n".join(agenda_lines(club, meeting)) + "\n")
    print("wrote the agenda for {} to {}".format(meeting.day.isoformat(), args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
