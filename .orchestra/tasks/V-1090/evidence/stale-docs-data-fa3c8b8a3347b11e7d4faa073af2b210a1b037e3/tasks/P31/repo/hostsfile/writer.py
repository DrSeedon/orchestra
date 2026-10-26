"""Write HostLine records back to a hosts file."""
import shutil
from pathlib import Path

from .model import HostLine, LineKind

ADDRESS_WIDTH = 15


def render_line(line: HostLine) -> str:
    """Turn one record back into a line of text.

    Args:
        line: The record to render.

    Returns:
        The line without a line break.
    """
    if line.kind is LineKind.BLANK:
        return ""
    if line.kind is LineKind.COMMENT:
        return f"# {line.comment}".rstrip()
    text = " ".join([line.address.ljust(ADDRESS_WIDTH), *line.names]).rstrip()
    if line.comment:
        text = f"{text}  # {line.comment}"
    return text


def render(lines: list[HostLine]) -> str:
    """Turn records into the text of a hosts file.

    Args:
        lines: The records, in file order.

    Returns:
        The text, with a line break after every line.
    """
    return "".join(f"{render_line(line)}\n" for line in lines)


def write_hosts(path: Path, lines: list[HostLine], backup: bool = True) -> None:
    """Write records to a hosts file.

    Args:
        path: The hosts file. Missing parent folders are created.
        lines: The records to write.
        backup: If true and the file exists, copy it to the same name with
            ".bak" added first.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    path.write_text(render(lines), encoding="utf-8")
