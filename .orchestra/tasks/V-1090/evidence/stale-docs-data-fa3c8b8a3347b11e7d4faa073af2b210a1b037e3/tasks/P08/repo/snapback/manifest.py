"""Snapshot manifests: every file in a snapshot with its SHA-256 hash."""
import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
FILES_DIR = "files"


def file_digest(file_name: str) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with open(file_name, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(source_dir: str) -> dict[str, str]:
    """Map each file below source_dir (relative, with "/" separators) to its digest."""
    entries = {}
    for folder, _dirs, files in os.walk(source_dir):
        for name in files:
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, source_dir).replace(os.sep, "/")
            entries[rel] = file_digest(full)
    logger.debug("manifest for %s has %d files", source_dir, len(entries))
    return dict(sorted(entries.items()))


def write_manifest(snapshot_dir: str, entries: dict[str, str]) -> None:
    """Write the manifest file of a snapshot."""
    target = os.path.join(snapshot_dir, MANIFEST_NAME)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "files": entries}, handle, indent=2)


def read_manifest(snapshot_dir: str) -> tuple[dict[str, str] | None, str]:
    """Read the manifest of a snapshot.

    Returns (entries, "") on success and (None, reason) on failure.
    """
    source = os.path.join(snapshot_dir, MANIFEST_NAME)
    if not os.path.isfile(source):
        return None, "no manifest in {}".format(snapshot_dir)
    try:
        with open(source, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, "manifest in {} is not valid JSON: {}".format(snapshot_dir, exc)
    if "files" not in data:
        return None, "manifest in {} has no file list".format(snapshot_dir)
    return data["files"], ""
