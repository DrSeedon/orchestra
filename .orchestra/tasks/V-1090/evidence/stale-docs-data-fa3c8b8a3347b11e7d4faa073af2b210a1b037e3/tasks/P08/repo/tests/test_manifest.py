import hashlib
import os

from snapback.manifest import build_manifest, file_digest, read_manifest, write_manifest


def test_file_digest(source):
    expected = hashlib.sha256(b"hello\n").hexdigest()
    assert file_digest(os.path.join(source, "notes.txt")) == expected


def test_build_manifest_uses_forward_slashes(source):
    entries = build_manifest(source)
    assert sorted(entries) == ["docs/plan.md", "notes.txt"]


def test_write_then_read(source, workdir):
    entries = build_manifest(source)
    write_manifest(workdir, entries)
    loaded, error = read_manifest(workdir)
    assert loaded == entries
    assert error == ""


def test_read_missing_manifest(workdir):
    loaded, error = read_manifest(workdir)
    assert loaded is None
    assert "no manifest" in error


def test_read_broken_manifest(workdir):
    with open(os.path.join(workdir, "manifest.json"), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    loaded, error = read_manifest(workdir)
    assert loaded is None
    assert "not valid JSON" in error
