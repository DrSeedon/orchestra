"""Look up, add and remove host names in a parsed hosts file."""
from dataclasses import replace

from .address import address_family, check_names, name_key
from .model import Family, HostLine, HostsFileError, LineKind


def _entry_family(line: HostLine) -> Family | None:
    try:
        return address_family(line.address)
    except HostsFileError:
        return None


def _maps(line: HostLine, key: str) -> bool:
    return line.is_entry and key in {name_key(name) for name in line.names}


def find_name(lines: list[HostLine], name: str) -> list[HostLine]:
    """Return the entry lines that map a host name.

    Args:
        lines: The parsed hosts file.
        name: The host name to look up. Case does not matter.

    Returns:
        The matching entry lines, in file order.
    """
    key = name_key(name)
    return [line for line in lines if _maps(line, key)]


def add_entry(lines: list[HostLine], address: str, names: list[str],
              comment: str = "") -> list[HostLine]:
    """Add an entry at the end of a parsed hosts file.

    Args:
        lines: The parsed hosts file. It is not changed.
        address: The IP address of the entry.
        names: The host names of the entry.
        comment: Comment text for the entry, or an empty string.

    Returns:
        A new list with the entry at the end.

    Raises:
        HostsFileError: If the address or a name is not valid, or a name is
            already mapped to an address of the same family.
    """
    family = address_family(address)
    check_names(names)
    for name in names:
        for line in find_name(lines, name):
            if _entry_family(line) is family:
                raise HostsFileError(f"{name} is already mapped on line {line.number}")
    number = lines[-1].number + 1 if lines else 1
    return [*lines, HostLine(number, LineKind.ENTRY, address, list(names), comment)]


def remove_name(lines: list[HostLine], name: str) -> list[HostLine]:
    """Remove a host name from every entry; drop entries left without names.

    Args:
        lines: The parsed hosts file. It is not changed.
        name: The host name to remove. Case does not matter.

    Returns:
        A new list without the name.

    Raises:
        HostsFileError: If no entry maps the name.
    """
    key = name_key(name)
    if not find_name(lines, name):
        raise HostsFileError(f"no entry maps {name}")
    result = []
    for line in lines:
        if not _maps(line, key):
            result.append(line)
            continue
        kept = [other for other in line.names if name_key(other) != key]
        if kept:
            result.append(replace(line, names=kept))
    return result
