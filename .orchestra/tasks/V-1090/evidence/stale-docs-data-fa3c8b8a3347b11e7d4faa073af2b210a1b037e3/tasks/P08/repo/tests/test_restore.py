import os
from datetime import datetime

from snapback.restore import restore_snapshot, verify_snapshot
from snapback.snapshot import create_snapshot

WHEN = datetime(2024, 3, 1, 9, 30, 0)


def test_restore_round_trip(source, backup_root, workdir):
    snapshot_dir, _ = create_snapshot(source, backup_root, "home", WHEN)
    target = os.path.join(workdir, "restored")
    ok, error = restore_snapshot(snapshot_dir, target)
    assert ok and error == ""
    with open(os.path.join(target, "docs", "plan.md"), encoding="utf-8") as handle:
        assert handle.read() == "# plan\n"


def test_verify_detects_changed_file(source, backup_root):
    snapshot_dir, _ = create_snapshot(source, backup_root, "home", WHEN)
    changed = os.path.join(snapshot_dir, "files", "notes.txt")
    with open(changed, "w", encoding="utf-8") as handle:
        handle.write("changed\n")
    ok, error = verify_snapshot(snapshot_dir)
    assert not ok
    assert "checksum mismatch" in error


def test_restore_refuses_non_empty_target(source, backup_root, workdir):
    snapshot_dir, _ = create_snapshot(source, backup_root, "home", WHEN)
    ok, error = restore_snapshot(snapshot_dir, source)
    assert not ok
    assert "not empty" in error
