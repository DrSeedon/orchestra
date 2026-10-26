"""Find photos with identical content."""
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, List

from photosort.scan import PhotoFile

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024


@dataclass
class DuplicateGroup:
    """Photos with the same content. The first relpath is treated as the original."""

    digest: str
    relpaths: List[str] = field(default_factory=list)


def file_digest(path: str) -> str:
    """Return the SHA-1 hex digest of the content of a file."""
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(photos: List[PhotoFile]) -> List[DuplicateGroup]:
    """Group the photos that have identical content.

    Only photos that share their size with another photo are read. Each group keeps
    the order of photos; only groups with two or more photos are returned, sorted
    by their first relpath.
    """
    by_size: Dict[int, List[PhotoFile]] = {}
    for photo in photos:
        by_size.setdefault(photo.size, []).append(photo)
    groups: Dict[str, DuplicateGroup] = {}
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        for photo in same_size:
            digest = file_digest(photo.path)
            groups.setdefault(digest, DuplicateGroup(digest)).relpaths.append(photo.relpath)
    found = [group for group in groups.values() if len(group.relpaths) > 1]
    found.sort(key=lambda group: group.relpaths[0])
    for group in found:
        logger.warning("%s has %d copies: %s", group.relpaths[0], len(group.relpaths) - 1,
                       ", ".join(group.relpaths[1:]))
    return found
