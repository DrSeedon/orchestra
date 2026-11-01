"""Read env files: one NAME=value pair per line."""
import os
import re

from envcheck.errors import EnvParseError

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXPORT = "export "


def parse_line(line: str, line_no: int) -> tuple[str, str] | None:
    """Parse one line of an env file.

    An ``export`` prefix is allowed. A value in single or double quotes loses its
    quotes; an unquoted value ends before " #".

    Args:
        line: The line without its line break.
        line_no: The number of the line, used in the error message.

    Returns:
        The pair (name, value), or None for a blank line or a comment.

    Raises:
        EnvParseError: The line has no "=" or the name is not valid.
    """
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith(_EXPORT):
        text = text[len(_EXPORT):].lstrip()
    name, sep, value = text.partition("=")
    name = name.strip()
    if not sep or not _NAME.fullmatch(name):
        raise EnvParseError(f"line {line_no}: expected NAME=value")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return name, value


def read_env_file(path: str) -> dict[str, str]:
    """Read an env file. A name that is set twice keeps its last value.

    Args:
        path: Path of the env file.

    Returns:
        The values by name, in file order.

    Raises:
        EnvParseError: A line is not valid. The message starts with the file name.
        OSError: The file cannot be read.
    """
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                pair = parse_line(line.rstrip("\n"), line_no)
            except EnvParseError as error:
                raise EnvParseError(f"{os.path.basename(path)}: {error}") from None
            if pair is not None:
                name, value = pair
                values[name] = value
    return values
