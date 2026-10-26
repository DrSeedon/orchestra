"""Validate link targets. Nothing here makes a network request."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXTERNAL_SCHEMES = {"http", "https"}


def classify(target: str) -> str:
    """Return the kind of a link target.

    :param target: link target as written in the document.
    :returns: ``"anchor"``, ``"external"``, ``"ignored"`` (mailto:, tel:, ...) or ``"local"``.
    """
    if target.startswith("#"):
        return "anchor"
    scheme = urlsplit(target).scheme.lower()
    if scheme in EXTERNAL_SCHEMES:
        return "external"
    if scheme:
        return "ignored"
    return "local"


def check_url_syntax(url: str) -> None:
    """Check that an external URL is well formed.

    :param url: an http or https URL.
    :raises ValueError: if the URL contains whitespace, has no usable host or has a bad port.
    """
    if any(char.isspace() for char in url):
        raise ValueError(f"whitespace in URL: {url}")
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError(f"URL has no host: {url}")
    if "." not in host and host != "localhost":
        raise ValueError(f"host is not a domain name: {host}")
    try:
        parts.port
    except ValueError:
        raise ValueError(f"bad port in URL: {url}") from None


def resolve_local(source: Path, target: str, root: Path | None = None) -> Path:
    """Resolve a local link target to a file path.

    Any ``?query`` or ``#fragment`` part is dropped before resolving.

    :param source: the document that contains the link.
    :param target: the link target as written.
    :param root: site root used for targets that start with ``/``.
    :returns: the absolute path the link points to.
    :raises ValueError: if the target has no file part, or starts with ``/`` without a root.
    """
    file_part = unquote(urlsplit(target).path)
    if not file_part:
        raise ValueError(f"link has no file part: {target}")
    if file_part.startswith("/"):
        if root is None:
            raise ValueError(f"root-relative link needs a site root: {target}")
        return (root / file_part.lstrip("/")).resolve()
    return (source.parent / file_part).resolve()


def check_local_target(source: Path, target: str, root: Path | None = None) -> Path:
    """Check that a local link points to an existing file or folder.

    :param source: the document that contains the link.
    :param target: the link target as written.
    :param root: site root used for targets that start with ``/``.
    :returns: the resolved path of the target.
    :raises FileNotFoundError: if nothing exists at the resolved path.
    """
    path = resolve_local(source, target, root)
    if not path.exists():
        raise FileNotFoundError(f"missing file: {target}")
    return path
