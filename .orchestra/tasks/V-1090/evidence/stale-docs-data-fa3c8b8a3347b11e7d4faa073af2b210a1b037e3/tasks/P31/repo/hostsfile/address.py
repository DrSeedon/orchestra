"""Checks for IP addresses and host names."""
import ipaddress
import re

from .model import Family, HostsFileError

MAX_NAME_LENGTH = 253
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def address_family(text: str) -> Family:
    """Return the address family of an IP address.

    Args:
        text: An IPv4 or IPv6 address, for example "10.0.0.5" or "::1".

    Returns:
        Family.IPV4 or Family.IPV6.

    Raises:
        HostsFileError: If the text is not an IP address.
    """
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        raise HostsFileError(f"not an IP address: {text}") from None
    return Family.IPV4 if parsed.version == 4 else Family.IPV6


def is_valid_name(name: str) -> bool:
    """Tell whether a host name is valid.

    A valid name has at most 253 characters and consists of labels that are
    separated by dots. Each label has 1 to 63 letters, digits or hyphens and
    does not start or end with a hyphen.

    Args:
        name: The host name to check.

    Returns:
        True if the name is valid.
    """
    if not name or len(name) > MAX_NAME_LENGTH:
        return False
    return all(_LABEL.fullmatch(label) for label in name.split("."))


def check_names(names: list[str]) -> None:
    """Make sure that a list of host names can go into an entry.

    Args:
        names: The host names of one entry.

    Raises:
        HostsFileError: If the list is empty or a name is not valid.
    """
    if not names:
        raise HostsFileError("an entry needs at least one host name")
    for name in names:
        if not is_valid_name(name):
            raise HostsFileError(f"not a valid host name: {name}")


def name_key(name: str) -> str:
    """Return the form of a host name that is used for comparisons.

    Args:
        name: A host name.

    Returns:
        The name in lower case, because host names do not depend on case.
    """
    return name.lower()
