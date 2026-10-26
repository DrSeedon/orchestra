"""Finding the snapshots stored in a backup root."""
import logging
import os
from datetime import datetime

from .snapshot import STAMP_FORMAT

logger = logging.getLogger(__name__)


def parse_stamp(folder_name: str) -> datetime | None:
    """Return the time encoded in a snapshot folder name, or None if it is not a stamp."""
    try:
        return datetime.strptime(folder_name, STAMP_FORMAT)
    except ValueError:
        return None


def list_snapshots(backup_root: str, name: str) -> tuple[list[str] | None, str]:
    """List the snapshot folders of one source, oldest first.

    Returns (folders, "") on success and (None, reason) when the source has no
    folder in the backup root. Entries that are not snapshot folders are skipped.
    """
    source_root = os.path.join(backup_root, name)
    if not os.path.isdir(source_root):
        return None, "no snapshots for {!r} in {}".format(name, backup_root)
    stamps = []
    for entry in os.listdir(source_root):
        if not os.path.isdir(os.path.join(source_root, entry)):
            continue
        if parse_stamp(entry) is None:
            logger.debug("skipping %s: not a snapshot folder", entry)
            continue
        stamps.append(entry)
    return [os.path.join(source_root, stamp) for stamp in sorted(stamps)], ""


def latest_snapshot(backup_root: str, name: str) -> tuple[str | None, str]:
    """Return (newest snapshot folder, "") or (None, reason)."""
    folders, error = list_snapshots(backup_root, name)
    if folders is None:
        return None, error
    if not folders:
        return None, "no snapshots for {!r} in {}".format(name, backup_root)
    return folders[-1], ""


def list_sources(backup_root: str) -> list[str]:
    """Return the names of all sources that have a folder in the backup root."""
    if not os.path.isdir(backup_root):
        return []
    return sorted(
        entry
        for entry in os.listdir(backup_root)
        if os.path.isdir(os.path.join(backup_root, entry))
    )
