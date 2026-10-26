"""Restoring snapshots and verifying them against their manifest."""
import logging
import os
import shutil

from .manifest import FILES_DIR, file_digest, read_manifest

logger = logging.getLogger(__name__)


def verify_snapshot(snapshot_dir: str) -> tuple[bool, str]:
    """Check every file of a snapshot against its manifest digest.

    Returns (True, "") when all files match and (False, reason) otherwise.
    """
    entries, error = read_manifest(snapshot_dir)
    if entries is None:
        return False, error
    for rel, expected in entries.items():
        stored = os.path.join(snapshot_dir, FILES_DIR, *rel.split("/"))
        if not os.path.isfile(stored):
            return False, "missing file in snapshot: {}".format(rel)
        if file_digest(stored) != expected:
            return False, "checksum mismatch: {}".format(rel)
    return True, ""


def restore_snapshot(snapshot_dir: str, target_dir: str) -> tuple[bool, str]:
    """Copy a verified snapshot into an empty or missing target directory.

    Returns (True, "") on success and (False, reason) on failure.
    """
    ok, error = verify_snapshot(snapshot_dir)
    if not ok:
        return False, error
    if os.path.isdir(target_dir) and os.listdir(target_dir):
        return False, "target directory is not empty: {}".format(target_dir)
    entries, error = read_manifest(snapshot_dir)
    if entries is None:
        return False, error
    for rel in entries:
        target = os.path.join(target_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(snapshot_dir, FILES_DIR, *rel.split("/")), target)
    logger.info("restored %d files from %s to %s", len(entries), snapshot_dir, target_dir)
    return True, ""
