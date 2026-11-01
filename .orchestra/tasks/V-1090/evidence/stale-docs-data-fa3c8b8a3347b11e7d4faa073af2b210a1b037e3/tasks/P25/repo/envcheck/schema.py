"""Read the schema file: the variables an env file sets, with their types."""
import os

from envcheck.errors import SchemaError
from envcheck.rules import TYPE_CHECKS

REQUIRED = "required"
OPTIONAL = "optional"


def parse_schema_line(text: str) -> tuple[str, dict]:
    """Parse one schema line of the form ``NAME TYPE [required|optional]``.

    Args:
        text: The line without comment and surrounding spaces.

    Returns:
        The pair (name, spec). spec has the keys "type" and "required".

    Raises:
        SchemaError: The line has the wrong number of words, an unknown type or
            an unknown word in place of required or optional.
    """
    parts = text.split()
    if len(parts) not in (2, 3):
        raise SchemaError(f"expected NAME TYPE [{REQUIRED}|{OPTIONAL}], got {text!r}")
    name, kind = parts[0], parts[1]
    need = parts[2] if len(parts) == 3 else REQUIRED
    if kind not in TYPE_CHECKS:
        raise SchemaError(f"unknown type {kind!r}, expected one of {', '.join(TYPE_CHECKS)}")
    if need not in (REQUIRED, OPTIONAL):
        raise SchemaError(f"expected {REQUIRED} or {OPTIONAL}, got {need!r}")
    return name, {"type": kind, "required": need == REQUIRED}


def load_schema(path: str) -> dict[str, dict]:
    """Read a schema file. Blank lines and text after "#" are ignored.

    Args:
        path: Path of the schema file.

    Returns:
        The spec of every variable by name, in file order.

    Raises:
        SchemaError: A line is not valid or a name appears twice.
        OSError: The file cannot be read.
    """
    schema: dict[str, dict] = {}
    base = os.path.basename(path)
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.split("#", 1)[0].strip()
            if not text:
                continue
            try:
                name, spec = parse_schema_line(text)
            except SchemaError as error:
                raise SchemaError(f"{base}:{line_no}: {error}") from None
            if name in schema:
                raise SchemaError(f"{base}:{line_no}: {name} appears twice")
            schema[name] = spec
    return schema
