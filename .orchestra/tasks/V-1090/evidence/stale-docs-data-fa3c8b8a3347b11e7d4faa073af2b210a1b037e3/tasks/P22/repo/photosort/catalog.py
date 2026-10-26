"""Write a CSV catalog of a photo folder.

Run as ``python -m photosort.catalog SOURCE OUTPUT_CSV``.
"""
import csv
import logging
import os
import sys
from typing import Dict, List

from photosort.dedupe import find_duplicates
from photosort.scan import PhotoFile, scan_photos, undated

logger = logging.getLogger(__name__)

CATALOG_COLUMNS = ["path", "size", "taken", "duplicate_of"]
USAGE = "usage: python -m photosort.catalog SOURCE OUTPUT_CSV"


def catalog_rows(photos: List[PhotoFile]) -> List[Dict[str, str]]:
    """Build one catalog row per photo, in the order of photos.

    duplicate_of names the first photo with the same content, or is empty.
    """
    original_of: Dict[str, str] = {}
    for group in find_duplicates(photos):
        for relpath in group.relpaths[1:]:
            original_of[relpath] = group.relpaths[0]
    rows = []
    for photo in photos:
        rows.append({
            "path": photo.relpath,
            "size": str(photo.size),
            "taken": photo.taken.isoformat() if photo.taken else "",
            "duplicate_of": original_of.get(photo.relpath, ""),
        })
    return rows


def write_catalog(rows: List[Dict[str, str]], output: str) -> None:
    """Write catalog rows to a CSV file, creating its folder when needed."""
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("wrote %d rows to %s", len(rows), output)


def main(argv: List[str]) -> int:
    """Run the catalog command and return its exit status."""
    if len(argv) != 2:
        logger.error(USAGE)
        return 2
    source, output = argv
    if not os.path.isdir(source):
        logger.error("not a folder: %s", source)
        return 2
    photos = scan_photos(source)
    missing = undated(photos)
    if missing:
        logger.warning("%d photos have no date in their file name", len(missing))
    write_catalog(catalog_rows(photos), output)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main(sys.argv[1:]))
