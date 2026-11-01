"""Work out which supplier an invoice file belongs to."""
import os
import re


def supplier_from_filename(path: str) -> str:
    """Return the supplier key for a file such as 'ACME_2024-03.csv' -> 'acme'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    name = re.split(r"[_-]\d", stem, maxsplit=1)[0].strip().lower()
    if not name or not name[0].isalpha():
        raise ValueError(f"cannot derive a supplier name from {path}")
    return name


def load_supplier_aliases(path: str) -> dict[str, str]:
    """Read 'alias = supplier' lines; a missing file means no aliases."""
    aliases: dict[str, str] = {}
    if not os.path.exists(path):
        return aliases
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if "=" not in text:
                raise ValueError(f"{path}:{line_no}: expected 'alias = supplier'")
            alias, supplier = (part.strip().lower() for part in text.split("=", 1))
            aliases[alias] = supplier
    return aliases


def resolve_supplier(path: str, aliases: dict[str, str]) -> str:
    """Return the supplier for a file, applying aliases."""
    name = supplier_from_filename(path)
    return aliases.get(name, name)
