"""Walk a photo folder and collect the photo files in it."""
import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from photosort.naming import date_from_name, is_photo

logger = logging.getLogger(__name__)


@dataclass
class PhotoFile:
    """One photo found under the scanned folder.

    path is the full path on disk; relpath is the path inside the scanned folder
    with "/" as separator; taken is the day from the file name, if any.
    """

    path: str
    relpath: str
    size: int
    taken: Optional[date]


def scan_photos(root: str) -> List[PhotoFile]:
    """Find all photos under root.

    Hidden folders (names that start with a dot) and files that are not photos are
    skipped. The result is sorted by relpath.
    """
    photos: List[PhotoFile] = []
    ignored = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in filenames:
            if filename.startswith(".") or not is_photo(filename):
                ignored += 1
                continue
            path = os.path.join(dirpath, filename)
            relpath = os.path.relpath(path, root).replace(os.sep, "/")
            photos.append(PhotoFile(path, relpath, os.path.getsize(path), date_from_name(filename)))
    photos.sort(key=lambda photo: photo.relpath)
    logger.info("found %d photos under %s, ignored %d other files", len(photos), root, ignored)
    return photos


def undated(photos: List[PhotoFile]) -> List[PhotoFile]:
    """Pick the photos whose file name holds no date, keeping their order."""
    return [photo for photo in photos if photo.taken is None]
