import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "snapback.prune"

STAMPS = ["20240229T120000", "20240301T093000", "20240302T093000", "20240303T093000",
          "20240304T093000"]
NO_MANIFEST = "20240229T120000"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def make_root(tmp_path):
    root = str(tmp_path / "backups")
    for stamp in STAMPS:
        folder = os.path.join(root, "home", stamp)
        write(os.path.join(folder, "files", "notes.txt"), "hello " + stamp + "\n")
        if stamp != NO_MANIFEST:
            write(os.path.join(folder, "manifest.json"),
                  json.dumps({"version": 1, "files": {"notes.txt": "0" * 64}}))
    os.makedirs(os.path.join(root, "home", "scratch"))
    write(os.path.join(root, "work", "20240101T000000", "manifest.json"),
          json.dumps({"version": 1, "files": {}}))
    return root


def run(root, name, keep, report):
    return subprocess.run(
        [sys.executable, "-m", ENTRY, root, name, str(keep), str(report)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def listing(root, name):
    return sorted(os.listdir(os.path.join(root, name)))


def test_prune_keeps_newest(tmp_path):
    root = make_root(tmp_path)
    report = tmp_path / "report.json"
    proc = run(root, "home", 2, report)
    assert proc.returncode == 0, proc.stderr
    with open(report, encoding="utf-8") as handle:
        assert json.load(handle) == {
            "kept": ["20240303T093000", "20240304T093000"],
            "removed": ["20240301T093000", "20240302T093000"],
            "skipped": ["20240229T120000"],
        }
    assert listing(root, "home") == [
        "20240229T120000", "20240303T093000", "20240304T093000", "scratch",
    ]
    assert listing(root, "work") == ["20240101T000000"]


def test_keep_more_than_available(tmp_path):
    root = make_root(tmp_path)
    report = tmp_path / "report.json"
    proc = run(root, "home", 10, report)
    assert proc.returncode == 0, proc.stderr
    with open(report, encoding="utf-8") as handle:
        assert json.load(handle) == {"kept": STAMPS, "removed": [], "skipped": []}
    assert listing(root, "home") == STAMPS + ["scratch"]


def test_keep_one(tmp_path):
    root = make_root(tmp_path)
    report = tmp_path / "report.json"
    proc = run(root, "home", 1, report)
    assert proc.returncode == 0, proc.stderr
    with open(report, encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["kept"] == ["20240304T093000"]
    assert data["removed"] == ["20240301T093000", "20240302T093000", "20240303T093000"]
    assert data["skipped"] == ["20240229T120000"]


def test_keep_below_one_fails(tmp_path):
    root = make_root(tmp_path)
    report = tmp_path / "report.json"
    for keep in (0, -1, "two"):
        proc = run(root, "home", keep, report)
        assert proc.returncode == 2
        assert not report.exists()
    assert listing(root, "home") == STAMPS + ["scratch"]


def test_source_without_snapshots_fails(tmp_path):
    root = make_root(tmp_path)
    os.makedirs(os.path.join(root, "empty", "scratch"))
    report = tmp_path / "report.json"
    for name in ("nobody", "empty"):
        proc = run(root, name, 1, report)
        assert proc.returncode == 2
        assert not report.exists()
