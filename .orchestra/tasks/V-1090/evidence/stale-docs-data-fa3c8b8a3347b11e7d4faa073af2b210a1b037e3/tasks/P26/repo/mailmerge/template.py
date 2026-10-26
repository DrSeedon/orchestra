"""Load mail templates and fill in their {{field}} placeholders."""
import re
from pathlib import Path
from typing import Optional

PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


def load_template(path: Path) -> str:
    """Read a template file. An empty template is an error."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{source.name}: template is empty")
    return text


def template_fields(text: str) -> list[str]:
    """Return the fields a template uses, in order of first use."""
    names: list[str] = []
    for match in PLACEHOLDER.finditer(text):
        if match.group(1) not in names:
            names.append(match.group(1))
    return names


def field_value(name: str, values: dict[str, str],
                defaults: Optional[dict[str, str]] = None) -> str:
    """Return the value of one field, taken from values first and from defaults second."""
    value = values.get(name, "").strip()
    if not value and defaults:
        value = defaults.get(name, "").strip()
    if not value:
        raise ValueError(f"no value for field {name!r}")
    return value


def render(text: str, values: dict[str, str],
           defaults: Optional[dict[str, str]] = None) -> str:
    """Fill every placeholder of a template.

    A field that is empty or missing in both values and defaults is an error.
    """
    return PLACEHOLDER.sub(lambda match: field_value(match.group(1), values, defaults), text)
