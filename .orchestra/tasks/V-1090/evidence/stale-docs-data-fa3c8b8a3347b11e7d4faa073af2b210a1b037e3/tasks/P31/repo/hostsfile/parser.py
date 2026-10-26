"""Parse the text of a hosts file into HostLine records."""
from pathlib import Path

from .model import HostLine, LineKind


def parse_line(text: str, number: int) -> HostLine:
    """Parse one line of a hosts file.

    The parser only splits the line into its parts. It does not check the
    address or the names, so a file with mistakes can still be read, shown
    and fixed.

    Args:
        text: The line without its line break.
        number: The line number, starting at 1.

    Returns:
        The parsed line. A line with an address but no names is an entry with
        an empty names list.
    """
    body, sep, comment = text.partition("#")
    fields = body.split()
    if not fields:
        kind = LineKind.COMMENT if sep else LineKind.BLANK
        return HostLine(number, kind, comment=comment.strip())
    return HostLine(number, LineKind.ENTRY, fields[0], fields[1:], comment.strip())


def parse_text(text: str) -> list[HostLine]:
    """Parse the full text of a hosts file.

    Args:
        text: The content of the file.

    Returns:
        One HostLine per line, in file order.
    """
    return [parse_line(line, number) for number, line in enumerate(text.splitlines(), start=1)]


def read_hosts(path: Path) -> list[HostLine]:
    """Read and parse a hosts file.

    Args:
        path: The hosts file.

    Returns:
        One HostLine per line of the file.
    """
    return parse_text(path.read_text(encoding="utf-8"))
