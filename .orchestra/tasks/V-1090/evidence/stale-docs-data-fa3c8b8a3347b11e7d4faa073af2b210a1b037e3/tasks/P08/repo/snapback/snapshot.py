"""Creating snapshots of a source directory inside a backup root."""
import logging
import os
import shutil
from datetime import datetime

from .manifest import FILES_DIR, build_manifest, write_manifest

logger = logging.getLogger(__name__)

STAMP_FORMAT = "%Y%m%dT%H%M%S"


def snapshot_stamp(when: datetime) -> str:
    """Return the folder name used for a snapshot taken at a given time."""
    return when.strftime(STAMP_FORMAT)


def create_snapshot(
    source_dir: str, backup_root: str, name: str, when: datetime | None = None
) -> tuple[str | None, str]:
    """Copy source_dir into <backup_root>/<name>/<stamp>/ and write its manifest.

    Returns (snapshot_dir, "") on success and (None, reason) on failure.
    """
    if not os.path.isdir(source_dir):
        return None, "source directory not found: {}".format(source_dir)
    if not name or os.sep in name or "/" in name:
        return None, "invalid source name: {!r}".format(name)
    stamp = snapshot_stamp(when or datetime.now())
    snapshot_dir = os.path.join(backup_root, name, stamp)
    if os.path.exists(snapshot_dir):
        return None, "snapshot already exists: {}".format(snapshot_dir)

    entries = build_manifest(source_dir)
    for rel in entries:
        target = os.path.join(snapshot_dir, FILES_DIR, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(source_dir, *rel.split("/")), target)
    os.makedirs(snapshot_dir, exist_ok=True)
    write_manifest(snapshot_dir, entries)
    logger.info("created snapshot %s with %d files", snapshot_dir, len(entries))
    return snapshot_dir, ""
