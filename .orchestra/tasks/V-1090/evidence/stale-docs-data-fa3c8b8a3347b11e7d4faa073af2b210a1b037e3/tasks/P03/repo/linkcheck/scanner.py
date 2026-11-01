"""Scan a folder of documents and collect link problems."""
from dataclasses import dataclass
from pathlib import Path

from linkcheck.extract import Link, extract_links
from linkcheck.validate import check_local_target, check_url_syntax, classify

DOCUMENT_SUFFIXES = (".md", ".markdown", ".html", ".htm")
SKIPPED_DIRS = {".git", "node_modules", "_build"}


@dataclass(frozen=True)
class Problem:
    """A broken or malformed link.

    :param link: the link that failed.
    :param message: why it failed.
    """

    link: Link
    message: str


def find_documents(root: Path) -> list[Path]:
    """Return every markdown and HTML document under a folder, sorted.

    :param root: folder to scan; build and VCS folders are skipped.
    :returns: document paths.
    :raises NotADirectoryError: if ``root`` is not a folder.
    """
    if not root.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    found = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in DOCUMENT_SUFFIXES or not path.is_file():
            continue
        if SKIPPED_DIRS.intersection(path.relative_to(root).parts):
            continue
        found.append(path)
    return found


def check_link(link: Link, root: Path) -> None:
    """Check a single link.

    In-page anchors and ignored schemes (mailto:, tel:, ...) are accepted as they are.

    :param link: the link to check.
    :param root: site root for root-relative targets.
    :raises ValueError: if an external URL is malformed or a local target is unusable.
    :raises FileNotFoundError: if a local target does not exist.
    """
    kind = classify(link.target)
    if kind == "external":
        check_url_syntax(link.target)
    elif kind == "local":
        check_local_target(link.source, link.target, root)


def check_document(path: Path, root: Path) -> list[Problem]:
    """Check every link of one document.

    :param path: the document.
    :param root: site root for root-relative targets.
    :returns: one problem per failing link.
    """
    problems = []
    for link in extract_links(path):
        try:
            check_link(link, root)
        except (ValueError, FileNotFoundError) as exc:
            problems.append(Problem(link, str(exc)))
    return problems


def check_tree(root: Path) -> tuple[list[Problem], int]:
    """Check every document under a folder.

    :param root: folder to scan; also used as the site root.
    :returns: all problems and the number of documents checked.
    """
    documents = find_documents(root)
    problems = []
    for document in documents:
        problems.extend(check_document(document, root))
    return problems, len(documents)
