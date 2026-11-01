import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "2024-01-05 08.00.00.png": b"png one",
    "IMG_20240315_101500.jpg": b"first march photo",
    "a/IMG_20240315_101500.jpg": b"second march photo",
    "scan.jpg": b"no date here",
    "trip/PXL_20231231_235959123.jpg": b"new year",
    "notes.txt": b"not a photo",
}


def make_tree(root, files):
    for relpath, content in files.items():
        path = os.path.join(root, *relpath.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "photosort.organize", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def plan_lines(dest):
    with open(os.path.join(dest, "plan.csv"), encoding="utf-8", newline="") as handle:
        return [line.rstrip("\r\n") for line in handle]


def exists(root, relpath):
    return os.path.isfile(os.path.join(root, *relpath.split("/")))


def test_organize_moves_dated_photos(tmp_path):
    source = os.path.join(str(tmp_path), "src")
    dest = os.path.join(str(tmp_path), "sorted")
    make_tree(source, FILES)
    result = run(source, dest)
    assert result.returncode == 0, result.stderr
    assert plan_lines(dest) == [
        "source,target,status",
        "2024-01-05 08.00.00.png,2024/01/2024-01-05 08.00.00.png,moved",
        "IMG_20240315_101500.jpg,2024/03/IMG_20240315_101500.jpg,moved",
        "a/IMG_20240315_101500.jpg,,skipped",
        "scan.jpg,,skipped",
        "trip/PXL_20231231_235959123.jpg,2023/12/PXL_20231231_235959123.jpg,moved",
    ]
    for target in ("2024/01/2024-01-05 08.00.00.png", "2024/03/IMG_20240315_101500.jpg",
                   "2023/12/PXL_20231231_235959123.jpg"):
        assert exists(dest, target)
    with open(os.path.join(dest, "2024", "03", "IMG_20240315_101500.jpg"), "rb") as handle:
        assert handle.read() == b"first march photo"
    assert not exists(source, "IMG_20240315_101500.jpg")
    assert not exists(source, "trip/PXL_20231231_235959123.jpg")
    for kept in ("a/IMG_20240315_101500.jpg", "scan.jpg", "notes.txt"):
        assert exists(source, kept)


def test_dry_run_moves_nothing(tmp_path):
    source = os.path.join(str(tmp_path), "src")
    dest = os.path.join(str(tmp_path), "sorted")
    make_tree(source, FILES)
    result = run(source, dest, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert plan_lines(dest) == [
        "source,target,status",
        "2024-01-05 08.00.00.png,2024/01/2024-01-05 08.00.00.png,planned",
        "IMG_20240315_101500.jpg,2024/03/IMG_20240315_101500.jpg,planned",
        "a/IMG_20240315_101500.jpg,,skipped",
        "scan.jpg,,skipped",
        "trip/PXL_20231231_235959123.jpg,2023/12/PXL_20231231_235959123.jpg,planned",
    ]
    assert sorted(os.listdir(dest)) == ["plan.csv"]
    for relpath in FILES:
        assert exists(source, relpath)


def test_existing_target_is_skipped(tmp_path):
    source = os.path.join(str(tmp_path), "src")
    dest = os.path.join(str(tmp_path), "sorted")
    make_tree(source, {"IMG_20240315_101500.jpg": b"incoming", "2024-03-16 09.00.00.jpg": b"other"})
    make_tree(dest, {"2024/03/IMG_20240315_101500.jpg": b"already here"})
    result = run(source, dest)
    assert result.returncode == 0, result.stderr
    assert plan_lines(dest) == [
        "source,target,status",
        "2024-03-16 09.00.00.jpg,2024/03/2024-03-16 09.00.00.jpg,moved",
        "IMG_20240315_101500.jpg,,skipped",
    ]
    with open(os.path.join(dest, "2024", "03", "IMG_20240315_101500.jpg"), "rb") as handle:
        assert handle.read() == b"already here"
    assert exists(source, "IMG_20240315_101500.jpg")


def test_missing_source_is_an_error(tmp_path):
    dest = os.path.join(str(tmp_path), "sorted")
    result = run(os.path.join(str(tmp_path), "missing"), dest)
    assert result.returncode == 2
    assert not os.path.exists(dest)
