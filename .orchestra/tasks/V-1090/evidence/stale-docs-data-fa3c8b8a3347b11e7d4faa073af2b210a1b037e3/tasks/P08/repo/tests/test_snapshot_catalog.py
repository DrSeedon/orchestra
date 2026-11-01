import os
from datetime import datetime

from snapback.catalog import latest_snapshot, list_snapshots, list_sources, parse_stamp
from snapback.snapshot import create_snapshot, snapshot_stamp

T1 = datetime(2024, 3, 1, 9, 30, 0)
T2 = datetime(2024, 3, 2, 9, 30, 0)


def test_create_snapshot_layout(source, backup_root):
    snapshot_dir, error = create_snapshot(source, backup_root, "home", T1)
    assert error == ""
    assert snapshot_dir == os.path.join(backup_root, "home", "20240301T093000")
    assert os.path.isfile(os.path.join(snapshot_dir, "manifest.json"))
    assert os.path.isfile(os.path.join(snapshot_dir, "files", "docs", "plan.md"))


def test_create_snapshot_failures(source, backup_root, workdir):
    missing, error = create_snapshot(os.path.join(workdir, "nope"), backup_root, "home", T1)
    assert missing is None and "not found" in error
    create_snapshot(source, backup_root, "home", T1)
    again, error = create_snapshot(source, backup_root, "home", T1)
    assert again is None and "already exists" in error


def test_list_and_latest(source, backup_root):
    create_snapshot(source, backup_root, "home", T2)
    create_snapshot(source, backup_root, "home", T1)
    os.makedirs(os.path.join(backup_root, "home", "scratch"))
    folders, error = list_snapshots(backup_root, "home")
    assert error == ""
    assert [os.path.basename(f) for f in folders] == ["20240301T093000", "20240302T093000"]
    latest, _ = latest_snapshot(backup_root, "home")
    assert latest == folders[-1]
    assert list_sources(backup_root) == ["home"]


def test_unknown_source(backup_root):
    folders, error = list_snapshots(backup_root, "work")
    assert folders is None
    assert "work" in error


def test_parse_stamp():
    assert parse_stamp(snapshot_stamp(T1)) == T1
    assert parse_stamp("scratch") is None
